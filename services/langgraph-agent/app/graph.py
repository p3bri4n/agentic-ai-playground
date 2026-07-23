"""
Graphe d'orchestration LangGraph.

Flux :
  1. retrieve_context   -> interroge Context Manager (RAG / mémoire)
  2. select_skill        -> interroge Skill Manager pour injecter un prompt de skill pertinent
  3. plan_task            -> si PLANNER_ENABLED (Itération 1, Phase 1 « cœur
     cognitif », voir docs/briefs/phase-1-coeur-cognitif.md), décompose
     l'objectif en sous-tâches JSON une seule fois par tâche ; no-op sinon
     ou si déjà planifié (voir AgentState.plan)
  4. call_llm             -> appelle le backend d'inférence (TabbyAPI par
     défaut, API OpenAI-compatible) avec function calling
  6. has_tool_calls       -> route vers require_approval, ou directement vers
     auto_call_tools si TOUS les tool_calls du tour sont auto-approuvés selon
     la politique par tiers (app/approval_policy.py, voir plus bas)
  7. require_approval (option) -> si le LLM demande un outil non auto-approuvé,
     met le graphe en pause (NodeInterrupt) tant qu'un humain n'a pas
     approuvé/refusé via l'état "approved"
  8. call_tools | auto_call_tools | reject_tools -> exécute l'outil via MCP
     Client (même logique partagée, voir _execute_tool_calls), ou synthétise
     un refus si l'humain a refusé. Seul auto_call_tools journalise dans le
     journal d'audit (Phase 2, voir app/audit_log.py) : call_tools est
     TOUJOURS atteint après un passage humain par require_approval CE
     tour-ci, déjà tracé dans la conversation.
  9. verify_action        -> si VERIFICATION_ENABLED (Itération 2, Phase 1
     « cœur cognitif »), compare le résultat du tour au success_criterion de
     la sous-tâche active du plan ; no-op sinon (reboucle direct sur
     call_llm, comme avant cette itération) — voir route_after_verification.
  10. replan_task | report_failure -> si une sous-tâche est marquée
     "echoue" : replanifie (budget REPLAN_BUDGET) ou rapporte un échec
     honnête à l'utilisateur (END) une fois ce budget épuisé.
  11. END                  -> réponse finale

Supervision humaine : par défaut, tout appel d'outil est soumis à
approbation (voir require_approval/reject_tools ci-dessous), à l'exception
des outils classés tier "read" ou "reversible" par app/approval_policy.py
(souris/capture d'écran GhostDesk, lecture filesystem/git, par défaut — voir
ce module pour le détail des tiers). Le graphe est donc compilé avec un
checkpointer (MemorySaver, en mémoire) pour pouvoir suspendre puis reprendre
l'exécution — au prix de perdre les approbations en attente si le service
redémarre (acceptable pour un usage local, voir README).
"""

import base64
import contextvars
import difflib
import io
import logging
import math
import os
import json
import re
import shlex
import uuid
from typing import Annotated, Optional, TypedDict
from urllib.parse import urljoin

import httpx
import langchain_openai.chat_models.base as _openai_base
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from PIL import Image
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import NodeInterrupt
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from app import approval_policy, audit_log, plan_validation

logger = logging.getLogger(__name__)

# Le raisonnement d'un modèle "thinking" arrive dans un champ dédié des
# deltas SSE, en plus de "content" — hors du format OpenAI standard, que
# langchain-openai ignore silencieusement (_convert_delta_to_message_chunk ne
# lit que "content"/"tool_calls"/"function_call"). Le NOM de ce champ diffère
# selon le backend : "reasoning" avec Ollama (modèles Qwen3+), "reasoning_
# content" avec llama-server (confirmé en conditions réelles avec le fork
# turboquant-webp servant Qwen3.6 — llama-server suit ici la convention
# DeepSeek-R1/OpenAI o1, pas celle d'Ollama). Sans gérer les deux noms, le
# raisonnement streamé par llama-server disparaîtrait silencieusement (aucune
# erreur, juste absent du flux) — vérifié par un vrai appel streamé avant ce
# correctif : les deltas ne contenaient que "reasoning_content", jamais
# "reasoning". On réinjecte le contenu trouvé (quel que soit le nom du champ)
# en le repliant dans "content", entouré de <think>...</think> (convention
# reconnue par Open WebUI pour afficher une bulle de pensée repliable), ce
# qui le fait apparaître dans le flux de streaming existant sans toucher à
# app/main.py.
#
# TabbyAPI (backend par défaut depuis la migration ExLlamaV3, voir README
# section Backend d'inférence) a son propre toggle `reasoning: true` côté
# config.yml, mais le NOM du champ SSE qu'il émet sur le fil n'a pas encore
# été vérifié empiriquement (voir tests_integration/CUDA-DIAGNOSTIC.md /
# plan d'implémentation tabbyapi, risque ouvert #3) — si ni "reasoning" ni
# "reasoning_content" ne matchent en conditions réelles, ajouter un troisième
# `or _dict.get(...)` ci-dessous une fois le nom réel confirmé par un appel
# streamé réel, pas deviné.
_think_state: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "_think_state", default=None
)
_original_convert_delta = _openai_base._convert_delta_to_message_chunk


def _convert_delta_with_reasoning(_dict, default_class):
    chunk = _original_convert_delta(_dict, default_class)
    state = _think_state.get()
    if state is None:
        return chunk
    reasoning = _dict.get("reasoning") or _dict.get("reasoning_content")
    real_content = chunk.content
    if reasoning:
        prefix = "<think>" if not state["opened"] else ""
        state["opened"] = True
        pieces = [prefix, reasoning]
        if real_content:
            # Ce delta contient à la fois la fin du raisonnement ET le début
            # de la réponse finale dans le MÊME chunk (observé avec
            # TabbyAPI/ExLlamaV3 — llama-server/Ollama séparaient toujours
            # les deux en chunks distincts, d'où ce bug invisible avant
            # cette migration). Sans ce cas, chunk.content écrasé par le
            # seul raisonnement juste en dessous jetait silencieusement la
            # vraie réponse — le tour se terminait alors sans contenu
            # visible, déclenchant à tort le filet de secours empty-answer.
            state["closed"] = True
            pieces.append("</think>\n\n")
            pieces.append(real_content)
        chunk.content = "".join(pieces)
    elif chunk.content and state["opened"] and not state["closed"]:
        state["closed"] = True
        chunk.content = "</think>\n\n" + chunk.content
    return chunk


_openai_base._convert_delta_to_message_chunk = _convert_delta_with_reasoning

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://tabbyapi:5000/v1")
CONTEXT_MANAGER_URL = os.environ.get("CONTEXT_MANAGER_URL", "http://context-manager:8002")
SKILL_MANAGER_URL = os.environ.get("SKILL_MANAGER_URL", "http://skill-manager:8001")
MCP_CLIENT_URL = os.environ.get("MCP_CLIENT_URL", "http://mcp-client:8003")

# Garde-fou fabrication d'URL (Phase 1, voir PLAN.md/HISTORY.md — cible n°1
# du point zéro Phase 0 : l'agent invente régulièrement des URL plausibles
# jamais observées — page-4.html sur un catalogue à 3 pages, un chemin de
# recherche inexistant... — plutôt que de suivre un lien réel du DOM).
BROWSER_NAVIGATE_GUARDRAIL = os.environ.get("BROWSER_NAVIGATE_GUARDRAIL", "true").lower() == "true"

# Feedback gradué (Phase 1c, voir HISTORY.md) : la 1b (liste complète des
# liens à CHAQUE rejet) a fait reculer T4/T7/T8 par rapport à la 1a — la
# liste complète était redondante (déjà dans le snapshot structuré) et
# alourdissait chaque rejet. Trois paliers par NOMBRE DE TENTATIVES
# fabriquées pour cette tâche (pas par sous-tâche — la Phase 1 complète,
# pas encore faite, introduira ce découpage plus fin) :
#   1-2  : message minimal, aucune liste (le snapshot l'a déjà).
#   3..LIMIT-1 : + les quelques liens les plus proches de l'URL fabriquée
#                (aide ciblée, pas un annuaire).
#   >=LIMIT : le feedback change de nature — pousse vers une conclusion
#             honnête d'absence plutôt que vers une énième supposition
#             (pont vers T7 : l'obstination devient un aveu d'échec légitime).
FABRICATION_LIMIT = int(os.environ.get("FABRICATION_LIMIT", "5"))

def _fabrication_feedback(fabricated_url: str, attempt_number: int, page_links: list) -> str:
    if attempt_number >= FABRICATION_LIMIT:
        # Plafond (Phase 1c) : redirection conditionnelle vers des "candidats
        # forts" tentée en Phase 1d puis SUSPENDUE (voir HISTORY.md) —
        # l'hypothèse motivant ce branchement (0a, vérification d'archive
        # T5/T8) n'a pas été confirmée par les séquences réellement
        # observées. Revient au message inconditionnel de 1c : au plafond,
        # conclure à l'absence est une réponse valide, point final. Le vrai
        # correctif T5 vit maintenant côté infra (volume de téléchargement
        # dédié, voir HISTORY.md "Phase 1d-révisée") plutôt que dans une
        # heuristique de similarité sur ce feedback.
        return (
            f"URL non observée (tentative n°{attempt_number}). Plusieurs tentatives vers des URL "
            "inexistantes. Si la cible ne figure dans aucune page observée, conclure qu'elle "
            "est introuvable est une réponse valide — ne continue pas à deviner des chemins."
        )
    if attempt_number >= 3:
        closest = difflib.get_close_matches(fabricated_url, page_links, n=8, cutoff=0.0)[:8]
        liens_txt = "\n".join(f"- {u}" for u in closest) or "(aucun lien connu pour l'instant)"
        return (
            f"URL non observée dans la page (tentative n°{attempt_number}) — utilise un lien "
            f"réellement présent dans le snapshot. Liens les plus proches de ce que tu cherchais :\n{liens_txt}"
        )
    return (
        "URL non observée sur cette page. Utilise un lien réellement présent dans le snapshot "
        "(l'inventaire complet des liens y figure déjà) — ne devine pas un chemin."
    )


def _repeated_strategy_feedback(tool_name: str) -> str:
    """
    Garde-fou "stratégie différente" (Itération 2, voir _execute_tool_calls) :
    la tentative précédente sur cette sous-tâche a déjà échoué la
    vérification post-action avec EXACTEMENT le même outil et les mêmes
    arguments — répéter l'identique ne peut pas donner un résultat
    différent.
    """
    return (
        f"Nouvelle tentative refusée : `{tool_name}` avec exactement les mêmes arguments qu'à la "
        "tentative précédente, déjà jugée insuffisante pour cette sous-tâche. Change de stratégie "
        "(autre outil, autres arguments, autre approche) plutôt que de répéter la même action."
    )


_URL_RE = re.compile(r"https?://[^\s'\")\]]+")
_SNAPSHOT_URL_LINE_RE = re.compile(r"/url:\s*(\S+)")
_PAGE_URL_LINE_RE = re.compile(r"Page URL:\s*(\S+)")

# Borne de sortie d'outil (Phase 1) : un résultat d'outil browser_* trop
# volumineux (page réelle dense, voir T8/T11 — dépassement de contexte LLM
# découvert en conditions réelles, voir HISTORY.md) est tronqué à la SOURCE,
# avant d'entrer dans l'historique de conversation. Distinct de la rétention
# d'images (Phase 2, MAX_IMAGES_IN_CONTEXT) : ceci borne la taille d'UN SEUL
# résultat d'outil, pas l'historique complet.
BROWSER_TOOL_OUTPUT_MAX_CHARS = int(os.environ.get("BROWSER_TOOL_OUTPUT_MAX_CHARS", "8000"))


def _clean_url(url: str) -> str:
    """Retire la ponctuation de fin de phrase accolée par erreur au match
    (ex. "http://exemple.com/page.html," dans une phrase française) — une
    URL réelle ne se termine normalement jamais par ces caractères."""
    return url.rstrip(",.;:")


def _extract_urls(text: str, base_url: Optional[str]) -> set:
    """URL absolues et relatives (résolues via base_url) trouvées dans un
    texte de résultat d'outil browser_* (snapshot Playwright au format YAML,
    "- /url: ...", ou texte libre contenant des URL absolues)."""
    found = {_clean_url(m) for m in _URL_RE.findall(text)}
    for match in _SNAPSHOT_URL_LINE_RE.findall(text):
        match = _clean_url(match)
        found.add(urljoin(base_url, match) if base_url else match)
    return found


def _extract_page_url(text: str) -> Optional[str]:
    match = _PAGE_URL_LINE_RE.search(text)
    return match.group(1) if match else None


def _task_scope_urls(messages: list) -> set:
    """Racines du périmètre de la tâche : URL mentionnées dans le premier
    message humain (voir tests_integration/test_web_tasks.py, convention de
    prompt — une tâche mentionne toujours l'URL du site cible)."""
    first_human = next((m for m in messages if getattr(m, "type", None) == "human"), None)
    if first_human is None or not isinstance(first_human.content, str):
        return set()
    return {_clean_url(m) for m in _URL_RE.findall(first_human.content)}


_AFFORDANCE_LINE_RE = re.compile(r'-\s*\'?(link|button|textbox|combobox|checkbox|option)\s+"([^"]*)"')

# Inventaire hiérarchisé (Phase 1d, point 2) : au-delà de ce nombre
# d'affordances, préserver la liste COMPLÈTE devient contre-productif — sur
# une vraie page Wikipédia (593 affordances, ~47000 caractères d'inventaire
# à elle seule), l'inventaire dépassait déjà largement le plafond de sortie
# et affamait TOUT le contenu descriptif, y compris le lien sémantique entre
# "Naissance" et "Muret" (voir HISTORY.md, vérification d'archive T8).
AFFORDANCE_THRESHOLD = int(os.environ.get("AFFORDANCE_THRESHOLD", "60"))
_NAV_KEYWORDS = {
    "suivant", "précédent", "precedent", "next", "previous", "prev", "page",
    "retour", "accueil", "home", "sommaire", "menu", "navigation",
}


def _is_nav_label(label: str) -> bool:
    lowered = label.lower()
    return any(kw in lowered for kw in _NAV_KEYWORDS)


def _extract_affordances_structured(text: str) -> list[dict]:
    """
    Inventaire structuré des éléments INTERACTIFS d'un snapshot (liens avec
    href, boutons, champs de formulaire). Une ligne "link/button/..." est
    suivie (dans les 2 lignes suivantes, format Playwright) d'une ligne
    "- /url: ..." si l'élément a une cible ; sinon (bouton, champ) elle est
    listée sans URL.
    """
    lines = text.splitlines()
    items = []
    for i, line in enumerate(lines):
        match = _AFFORDANCE_LINE_RE.search(line)
        if not match:
            continue
        kind, label = match.groups()
        url = None
        for lookahead in lines[i + 1 : i + 3]:
            url_match = _SNAPSHOT_URL_LINE_RE.search(lookahead)
            if url_match:
                url = _clean_url(url_match.group(1))
                break
        items.append({"kind": kind, "label": label, "url": url})
    return items


def _format_affordance(item: dict) -> str:
    # Garde le motif littéral "/url: <cible>" (pas "-> url") : ce bloc
    # repasse ensuite par _extract_urls (voir _execute_tool_calls), qui
    # reconnaît spécifiquement ce motif pour les liens relatifs — un autre
    # format y serait invisible et casserait le suivi observed_urls sur
    # tout résultat tronqué.
    return f'- {item["kind"]} "{item["label"]}"' + (f' /url: {item["url"]}' if item["url"] else "")


def _extract_affordances(text: str) -> list[str]:
    """Voir _truncate_browser_result : cet inventaire est TOUJOURS conservé
    intégralement en dessous d'AFFORDANCE_THRESHOLD éléments — au-delà,
    _prioritize_affordances hiérarchise plutôt que de tout garder (voir
    ce module, HISTORY.md, "le tronquage affame la navigation")."""
    return [_format_affordance(i) for i in _extract_affordances_structured(text)]


def _prioritize_affordances(items: list[dict], objective: str) -> tuple[list[str], int]:
    """
    Au-delà d'AFFORDANCE_THRESHOLD : la pagination/navigation reste
    TOUJOURS intégrale (jamais le goulot), les liens de zone de contenu
    sont triés par proximité avec l'objectif de la tâche courante (le
    prompt initial, faute de sous-tâches explicites — Phase 1 complète pas
    encore faite) et plafonnés ; le reste est compté, pas listé.
    """
    nav = [i for i in items if _is_nav_label(i["label"])]
    content = [i for i in items if not _is_nav_label(i["label"])]
    if objective:
        content.sort(
            key=lambda i: difflib.SequenceMatcher(None, i["label"].lower(), objective.lower()).ratio(),
            reverse=True,
        )
    kept_content = content[:AFFORDANCE_THRESHOLD]
    elided = len(content) - len(kept_content)
    lines = [_format_affordance(i) for i in nav] + [_format_affordance(i) for i in kept_content]
    return lines, elided


def _truncate_browser_result(result: dict, max_chars: int, objective: str = "") -> dict:
    """
    Tronque un résultat d'outil browser_* trop volumineux SANS jamais perdre
    l'inventaire des affordances PERTINENTES (voir _extract_affordances /
    _prioritize_affordances) : celui-ci est placé en tête, avant le contenu
    (potentiellement tronqué). Le budget max_chars s'applique au CONTENU,
    pas à l'inventaire — si l'inventaire (déjà hiérarchisé si besoin) dépasse
    quand même max_chars, il reste entier : préserver la navigation prime
    sur le respect strict du plafond dans ce cas rare.
    """
    content = result.get("content")
    if not isinstance(content, list):
        return result
    new_content = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and len(block.get("text", "")) > max_chars:
            structured = _extract_affordances_structured(block["text"])
            if len(structured) > AFFORDANCE_THRESHOLD:
                formatted, elided = _prioritize_affordances(structured, objective)
                elided_note = (
                    f"\n(+ {elided} liens de contenu supplémentaires non affichés, triés par pertinence)"
                    if elided
                    else ""
                )
            else:
                formatted, elided_note = [_format_affordance(i) for i in structured], ""
            page_url = _extract_page_url(block["text"])
            # La ligne "Page URL: ..." elle-même est préservée en tête,
            # jamais tronquée : nécessaire pour résoudre les liens relatifs
            # de l'inventaire ci-dessous (voir _extract_urls, base_url).
            page_url_line = f"Page URL: {page_url}\n" if page_url else ""
            affordances_block = (
                (
                    page_url_line
                    + "### Éléments interactifs (liens/boutons/champs)\n"
                    + "\n".join(formatted)
                    + elided_note
                    + "\n\n"
                )
                if formatted
                else page_url_line
            )
            remaining = max(max_chars - len(affordances_block), 0)
            block = {
                **block,
                "text": (
                    affordances_block
                    + block["text"][:remaining]
                    + f"\n[...contenu tronqué à {remaining} caractères (éléments interactifs ci-dessus préservés)...]"
                ),
            }
        new_content.append(block)
    return {**result, "content": new_content}

# Format transmis au LLM pour les résultats image d'outil (screen_shot
# GhostDesk, format WebP natif) : vide (le défaut) reconvertit
# systématiquement en PNG — le backend par défaut (TabbyAPI/ExLlamaV3,
# voir README section Backend d'inférence) n'est pas connu pour décoder le
# WebP nativement (à vérifier empiriquement, voir plan d'implémentation
# tabbyapi, risque ouvert #2 ; nécessaire de toute façon avec Ollama, dont
# le décodeur mtmd échoue explicitement sur le WebP). "webp" ne s'active
# qu'avec le backend alternatif llama-server, dont le fork llama.cpp décode
# le WebP nativement (voir _to_png_data_uri plus bas et le tableau des bugs
# du README).
IMAGE_FORMAT_PASSTHROUGH = os.environ.get("IMAGE_FORMAT_PASSTHROUGH", "").lower() == "webp"

# Budget cumulé d'appels d'outils pour une même tâche : partagé sur toute la
# chaîne d'approbations d'un thread, PAS remis à zéro entre deux tours
# "approuver" (tool_iterations ne repart de 0 que sur un tout nouveau message
# utilisateur, voir _resolve_run dans app/main.py) — un ancien défaut de 5
# s'épuisait après 2-3 aller-retours d'approbation à peine, avant même
# d'atteindre la boucle GhostDesk auto-approuvée (capture/clic) qui consomme
# elle seule 2 itérations par geste. Dépassement signalé explicitement à
# l'utilisateur plutôt que silencieux (voir _current_answer, app/main.py).
MAX_TOOL_ITERATIONS = int(os.environ.get("MAX_TOOL_ITERATIONS", "20"))

# Politique d'approbation par tiers de réversibilité (voir
# app/approval_policy.py) : un tour est auto-approuvé si TOUS ses tool_calls
# sont en tier "read" ou "reversible" ; un tour mixte (même un seul outil en
# tier "sensitive") reste entièrement soumis à approbation, par sécurité —
# pas d'approbation partielle par outil. AUTO_APPROVED_TOOLS (ancienne
# variable d'env) continue de fonctionner comme override rétrocompatible,
# géré dans approval_policy.tool_tier().

# Nombre de tours auto-approuvés consécutifs tolérés avant de forcer malgré
# tout un passage par require_approval, même si tous les tool_calls du tour
# restent auto-approuvés (tier "read"/"reversible") — le garde-fou contre le
# clavier virtuel : un clic seul est anodin, mais une SUITE de clics peut
# composer une saisie complète via un clavier virtuel à l'écran, contournant
# de fait l'exclusion de key_type/key_press (tier "sensitive"). Sans plafond,
# une longue suite de clics pourrait au final saisir n'importe quel texte
# sans jamais qu'un humain ne valide quoi que ce soit. Remis à 0 à chaque
# passage réel par require_approval (voir cette fonction plus bas), pas
# seulement au début d'une nouvelle tâche — contrairement à tool_iterations,
# qui lui mesure un budget total et non un nombre de tours consécutifs SANS
# supervision humaine.
AUTO_APPROVAL_STREAK_LIMIT = int(os.environ.get("AUTO_APPROVAL_STREAK_LIMIT", "6"))

# Rétention d'images dans l'historique soumis au LLM : chaque screenshot
# GhostDesk (screen_shot) ajoute un message multimodal coûteux en tokens
# visuels (voir _split_image_blocks) ; sur une boucle capture/clic répétée,
# les conserver TOUTES finit par saturer le contexte pour un intérêt
# quasi nul (seule la capture la plus récente reflète l'état actuel de
# l'écran). Ne garde que les MAX_IMAGES_IN_CONTEXT dernières images dans ce
# qui est envoyé au LLM ; les précédentes sont remplacées par un texte
# indicatif — uniquement pour CET appel (voir _apply_image_retention),
# jamais persisté dans l'état du graphe/checkpointer : l'historique complet
# (avec toutes les images d'origine) reste inchangé et consultable/rejoué.
MAX_IMAGES_IN_CONTEXT = int(os.environ.get("MAX_IMAGES_IN_CONTEXT", "1"))
IMAGE_RETENTION_PLACEHOLDER = "[screenshot antérieure supprimée]"

# Nœud planificateur (Itération 1, Phase 1 « cœur cognitif » — voir
# docs/briefs/phase-1-coeur-cognitif.md). Défaut désactivé : un appel LLM
# supplémentaire en tête de CHAQUE tâche casserait la quasi-totalité des
# tests existants qui mockent une séquence FIXE de réponses sur
# /v1/chat/completions (voir plan_task plus bas) — même convention que
# ADAPTIVE_THINKING/IMAGE_FORMAT_PASSTHROUGH : off par défaut, à activer
# explicitement pour mesurer le mécanisme en conditions réelles.
PLANNER_ENABLED = os.environ.get("PLANNER_ENABLED", "false").lower() == "true"

# Vérification post-action + budget d'échec (Itération 2, Phase 1 « cœur
# cognitif » — voir docs/briefs/phase-1-coeur-cognitif.md). N'A D'EFFET QUE
# SI PLANNER_ENABLED EST AUSSI ACTIVÉ : la vérification compare le résultat
# d'un tour d'outils au success_criterion de la sous-tâche ACTIVE du plan
# (voir verify_action plus bas) — sans plan, rien à vérifier. Défaut
# désactivé pour la même raison que PLANNER_ENABLED : un appel LLM juge
# supplémentaire par tour d'outils casserait les tests existants qui
# mockent une séquence fixe de réponses.
VERIFICATION_ENABLED = os.environ.get("VERIFICATION_ENABLED", "false").lower() == "true"
# Tentatives par sous-tâche avant de la marquer "echoue" (voir verify_action).
SUBTASK_ATTEMPT_BUDGET = int(os.environ.get("SUBTASK_ATTEMPT_BUDGET", "3"))
# Replanifications tolérées pour une même tâche avant d'abandonner
# honnêtement (voir replan_task/report_failure) plutôt que de boucler à
# l'infini ou de prétendre un faux succès.
REPLAN_BUDGET = int(os.environ.get("REPLAN_BUDGET", "2"))

# Pipeline de validation du plan (Itération 3, Phase 1 « cœur cognitif » —
# voir docs/briefs/phase-1-coeur-cognitif.md et app/plan_validation.py).
# N'A D'EFFET QUE SI PLANNER_ENABLED EST AUSSI ACTIVÉ. Défaut désactivé,
# même raison que PLANNER_ENABLED/VERIFICATION_ENABLED : casserait les
# tests existants qui mockent une séquence fixe de réponses.
PLAN_VALIDATION_ENABLED = os.environ.get("PLAN_VALIDATION_ENABLED", "false").lower() == "true"
# Juge LLM du plan (heuristiques déjà passées, coûteux — un appel LLM par
# validation). CLAUSE DE RETRAIT (brief) : si une campagne live montre que
# ce juge n'attrape rien que les heuristiques ne voyaient pas, désactivé
# par défaut et consigné — voir HISTORY.md, Itération 3, pour le résultat
# de cette mesure et la valeur par défaut retenue en conséquence.
PLAN_JUDGE_ENABLED = os.environ.get("PLAN_JUDGE_ENABLED", "false").lower() == "true"
# "Rejet motivé → retour planificateur, max 2 cycles puis escalade
# humaine" (brief) : nombre de rejets (heuristiques OU juge) tolérés avant
# qu'un humain ne tranche (require_plan_approval, avec les motifs de rejet
# affichés) plutôt que de laisser le planificateur boucler indéfiniment.
PLAN_VALIDATION_CYCLES_MAX = 2

# Qwen3.6 raisonne par défaut sur chaque tour (balises de pensée étendue) —
# utile pour une décision initiale, coûteux en latence/tokens pour une
# boucle perception-action rapide (capture -> clic -> capture...) où chaque
# tour n'a qu'à décider "où cliquer ensuite" sans reconsidérer toute la
# tâche. Si ADAPTIVE_THINKING est activé, /no_think est injecté (system
# prompt transitoire, non persisté — voir _apply_adaptive_thinking) quand
# TOUS les tool_calls du tour précédent étaient auto-approuvés (même
# politique par tiers que has_tool_calls, voir approval_policy.py) ; le
# thinking normal reste actif pour le premier tour d'une tâche ou dès qu'un
# outil sensible est en jeu, où le raisonnement a le plus de valeur.
ADAPTIVE_THINKING = os.environ.get("ADAPTIVE_THINKING", "false").lower() == "true"
NO_THINK_DIRECTIVE = "/no_think"

# Le VLM servi (Qwen3.6 MoE) raisonne bien mais localise mal : son grounding
# visuel (viser le bon pixel d'un élément à l'écran) reste imprécis, sans
# OCR/détection d'éléments UI dédiée (voir README, Limites connues assumées).
# find_text/read_screen (services/ocr-service, tier lecture — voir
# approval_policy.py) compensent avec des coordonnées OCR exactes. Consigne
# transitoire (jamais persistée dans l'état du graphe, même principe que
# NO_THINK_DIRECTIVE ci-dessus) plutôt qu'une modification du prompt système
# par tour : reste valable identiquement sur toute la conversation.
GROUNDING_DIRECTIVE = (
    "Pour cliquer sur un élément contenant du texte, appelle d'abord "
    "find_text pour obtenir ses coordonnées exactes plutôt que d'estimer "
    "visuellement leur position — réserve l'estimation visuelle aux "
    "éléments sans texte (icônes)."
)

# Chemin de consommation de fichier DOCUMENTÉ (Phase 1d-révisée, voir
# HISTORY.md, T5) : un téléchargement déclenché dans le navigateur atterrit
# dans un volume désormais partagé en lecture seule avec le serveur MCP
# filesystem (voir docker-compose.yml, --output-dir/agent-downloads), sous
# /downloads — jamais dans le filesystem du conteneur playwright-mcp
# lui-même (fetch()/browser_evaluate comme canal de transfert de fichier a
# été explicitement écarté, voir HISTORY.md : ce n'est pas la primitive
# d'un outil de lecture). Donner le chemin réel plutôt que de laisser le
# modèle en deviner un (observé : /app/.playwright-mcp/, /.playwright-mcp/
# — tous deux faux) est l'anti-fabrication directe pour ce cas.
DOWNLOAD_DIRECTIVE = (
    "Pour un fichier à télécharger (lien/bouton de téléchargement) : "
    "déclenche le téléchargement dans le navigateur, puis lis son contenu "
    "via l'outil filesystem read_file sous /downloads/<nom_du_fichier> — "
    "jamais via browser_navigate/browser_evaluate vers un chemin du "
    "navigateur, que tu ne peux pas connaître à l'avance."
)

# Filet de sécurité (bug réel observé en usage réel avec llama-server —
# fork turboquant-webp — sur la tâche "va sur wikipedia.org et cherche
# l'article sur la ville de toulouse", voir README, tableau des bugs) : un
# modèle peut terminer un tour SANS tool_calls structuré ET sans texte de
# réponse visible.
#
# Cause racine confirmée en lisant le parseur du fork
# (common/chat-auto-parser-generator.cpp) : le raisonnement (<think>...)
# est capturé comme texte LIBRE, NON contraint par la grammaire, jusqu'à
# rencontrer la balise fermante </think> — la grammaire stricte du
# tool-calling n'est appliquée qu'APRÈS cette balise. Si le modèle "tente"
# un appel d'outil en prose (ex. syntaxe <tool_call><function=...> qu'il a
# vue rendue par le template pour ses propres tours précédents) SANS avoir
# fermé </think> au préalable — typiquement après un raisonnement anormalement
# long/répétitif, à rapprocher de la dérive sémantique déjà documentée pour
# Ollama — cette tentative reste piégée dans la zone non contrainte et
# n'est jamais reconnue comme un vrai tool_calls OpenAI. Confirmé
# NON-déterministe par ailleurs (rejouer le MÊME prompt donne tantôt un
# tool_calls correct, tantôt cet échec) et confirmé résolu par
# ADAPTIVE_THINKING/no_think (qui évite entièrement ce chemin de code
# vulnérable, voir plus haut) — mais /no_think ne s'injecte qu'à partir du
# tour SUIVANT un tour auto-approuvé, pas sur le tout premier tour d'une
# tâche, là où le bug a justement été observé.
#
# Deux mitigations complémentaires, aucune ne corrigeant la cause côté
# modèle/serveur (hors de portée ici) :
#   1. has_tool_calls reboucle automatiquement sur call_llm jusqu'à
#      MAX_EMPTY_ANSWER_RETRIES fois avant d'abandonner (voir cette
#      fonction plus bas) — budget cumulé pour toute la tâche, comme
#      tool_iterations, pas remis à zéro à chaque tentative.
#   2. _extract_fallback_tool_call (voir plus bas) : avant même de compter
#      ce tour comme un échec, tente d'extraire un appel <tool_call> piégé
#      dans le texte et de le reconstruire en tool_calls structuré — quand
#      ça réussit, le tour continue normalement (approbation, exécution...)
#      sans jamais consommer de retry ni afficher la notice de repli.
# Au-delà des deux, app/main.py affiche une notice explicite
# (_format_empty_answer_notice) plutôt que de laisser la conversation
# silencieuse.
MAX_EMPTY_ANSWER_RETRIES = int(os.environ.get("MAX_EMPTY_ANSWER_RETRIES", "1"))

# Forfait de tokens par image dans l'estimation de composition du contexte
# (voir describe_context/POST /context, services/dashboard) : un compte exact
# dépendrait du tokenizer visuel du modèle servi (hors de portée ici, voir
# README, Hors périmètre) — une constante suffit pour un ordre de grandeur
# affiché sur le dashboard d'observabilité.
IMAGE_TOKEN_ESTIMATE = int(os.environ.get("IMAGE_TOKEN_ESTIMATE", "1500"))


def estimate_tokens(text: str) -> int:
    """
    Estimation grossière (~3.5 caractères/token, ordre de grandeur pour
    l'anglais/français mélangés), pas un tokenizer exact — utilisée
    uniquement par POST /context pour le dashboard d'observabilité
    (services/dashboard), qui affiche des tendances plutôt que des comptes
    exacts (voir README, Hors périmètre : tokenizer exact explicitement
    écarté).
    """
    if not text:
        return 0
    return math.ceil(len(text) / 3.5)

# Reconnaît un appel d'outil écrit en prose au format XML-ish de Qwen
# (<tool_call><function=NOM><parameter=CLE>VALEUR</parameter>...</function>
# </tool_call>), tel qu'observé piégé dans reasoning_content en usage réel.
# DOTALL pour capturer des valeurs de paramètre multi-lignes (ex. texte à
# taper contenant un saut de ligne).
_FALLBACK_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*<function=([a-zA-Z0-9_]+)>(.*?)</function>\s*</tool_call>", re.DOTALL
)
_FALLBACK_PARAMETER_RE = re.compile(
    r"<parameter=([a-zA-Z0-9_]+)>(.*?)</parameter>", re.DOTALL
)


def _extract_fallback_tool_call(content: str) -> Optional[dict]:
    """
    Tente d'extraire un tool_call valide depuis du texte (reasoning ou
    content) quand le modèle en a écrit un en prose au lieu de le faire
    reconnaître par la grammaire du serveur (voir le commentaire de
    MAX_EMPTY_ANSWER_RETRIES ci-dessus pour la cause racine). Best-effort :
    un seul appel reconnu par tour (le premier trouvé), aucune validation
    contre le schéma JSON de l'outil — call_tools/mcp-client échoueront
    proprement si les arguments extraits sont incorrects, comme pour un
    tool_call normalement structuré. Retourne None si rien de reconnaissable
    n'est trouvé.
    """
    match = _FALLBACK_TOOL_CALL_RE.search(content or "")
    if not match:
        return None
    tool_name = match.group(1)
    params_blob = match.group(2)
    arguments = {
        key: value.strip() for key, value in _FALLBACK_PARAMETER_RE.findall(params_blob)
    }
    return {"name": tool_name, "args": arguments, "id": f"fallback_{uuid.uuid4().hex[:12]}"}

# Le "?" final rend la balise fermante optionnelle : couvre aussi bien le
# contenu déjà persisté par call_llm (toujours refermé avant retour) que du
# texte encore en cours de streaming côté app/main.py (potentiellement pas
# encore refermé au moment du test).
_THINK_BLOCK_RE = re.compile(r"<think>.*?(</think>|\Z)", re.DOTALL)


def has_visible_answer(content: str) -> bool:
    """Reste-t-il du texte hors balise <think> ? Utilisé par has_tool_calls
    (retry automatique) et app/main.py (notice de réponse vide)."""
    return bool(_THINK_BLOCK_RE.sub("", content or "").strip())


# Nœud planificateur (Itération 1, voir plan_task plus bas) : reconnaît un
# éventuel enrobage ```json ... ``` / ``` ... ``` autour de la réponse — le
# modèle peut envelopper le JSON malgré la consigne de sortie brute, comme
# déjà observé pour d'autres formats de sortie dans ce fichier (voir
# _extract_fallback_tool_call ci-dessus).
_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?(.*?)\n?```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    match = _CODE_FENCE_RE.match(text.strip())
    return match.group(1).strip() if match else text.strip()


class PlanValidationError(ValueError):
    """Levée par _validate_plan_json : réponse du planificateur inexploitable."""


_PLAN_SUBTASKS_MIN = 1
_PLAN_SUBTASKS_MAX = 8


def _validate_plan_json(raw: str) -> list[dict]:
    """
    Schéma validé PROGRAMMATIQUEMENT (Itération 1) : retire <think>...</think>
    puis un éventuel enrobage de fences, exige {"sous_taches": [{"description":...,
    "critere_succes":..., "outils": [...]}, ...]}, 1 à 8 éléments,
    description/critère non vides. `outils` optionnelle côté LLM (repli sur
    liste vide) — sert de base concrète au pipeline de validation
    (Itération 3, app/plan_validation.py : existence/tier des outils
    déclarés), sans quoi une sous-tâche purement rédactionnelle (ex.
    "formuler la réponse finale") n'aurait pas de représentation valide.
    Lève PlanValidationError avec un motif explicite sinon — jamais un plan
    partiellement construit à partir d'une réponse invalide.
    """
    text = _strip_code_fence(_THINK_BLOCK_RE.sub("", raw or ""))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanValidationError(f"JSON invalide : {exc}") from exc
    subtasks = data.get("sous_taches") if isinstance(data, dict) else None
    if not isinstance(subtasks, list):
        raise PlanValidationError("clé 'sous_taches' (liste) absente ou invalide")
    if not (_PLAN_SUBTASKS_MIN <= len(subtasks) <= _PLAN_SUBTASKS_MAX):
        raise PlanValidationError(
            f"nombre de sous-tâches hors bornes ({len(subtasks)}, attendu "
            f"{_PLAN_SUBTASKS_MIN}-{_PLAN_SUBTASKS_MAX})"
        )
    validated = []
    for i, item in enumerate(subtasks):
        if not isinstance(item, dict):
            raise PlanValidationError(f"sous-tâche {i} n'est pas un objet JSON")
        description = item.get("description")
        critere = item.get("critere_succes")
        if not isinstance(description, str) or not description.strip():
            raise PlanValidationError(f"sous-tâche {i} : description manquante ou vide")
        if not isinstance(critere, str) or not critere.strip():
            raise PlanValidationError(f"sous-tâche {i} : critere_succes manquant ou vide")
        outils = item.get("outils")
        if outils is None:
            outils = []
        if not isinstance(outils, list) or not all(isinstance(t, str) for t in outils):
            raise PlanValidationError(f"sous-tâche {i} : outils doit être une liste de strings")
        validated.append(
            {
                "description": description.strip(),
                "success_criterion": critere.strip(),
                "tools": [t.strip() for t in outils if t.strip()],
            }
        )
    return validated


PLANNER_SYSTEM_PROMPT = (
    "Tu es le planificateur d'un agent qui accomplit des tâches web. À "
    "partir de l'objectif de l'utilisateur, décompose-le en 1 à 8 "
    "sous-tâches concrètes et vérifiables. Réponds UNIQUEMENT par un JSON "
    'de la forme {"sous_taches": [{"description": "...", "critere_succes": '
    '"...", "outils": ["nom_outil", ...]}, ...]}, rien d\'autre : pas de '
    "texte avant/après, pas de balise <think>, pas de bloc de code. "
    '"outils" liste les noms des outils que tu comptes utiliser pour cette '
    "sous-tâche (liste vide si aucun, ex. une sous-tâche purement "
    "rédactionnelle)."
)


class PlanJudgeValidationError(ValueError):
    """Levée par _validate_judge_json : verdict du juge de plan inexploitable."""


def _validate_judge_json(raw: str) -> dict:
    """
    Schéma validé PROGRAMMATIQUEMENT (Itération 3, même pipeline que
    _validate_plan_json/_validate_verification_json) : exige
    {"faisable": bool}, "risques"/"etapes_manquantes" optionnelles (repli
    sur liste vide si absentes/mal formées — accessoires pour la
    visibilité, pas pour la décision).
    """
    text = _strip_code_fence(_THINK_BLOCK_RE.sub("", raw or ""))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanJudgeValidationError(f"JSON invalide : {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("faisable"), bool):
        raise PlanJudgeValidationError("clé 'faisable' (bool) absente ou invalide")
    risques = data.get("risques")
    etapes = data.get("etapes_manquantes")
    return {
        "faisable": data["faisable"],
        "risques": [r for r in risques if isinstance(r, str)] if isinstance(risques, list) else [],
        "etapes_manquantes": [e for e in etapes if isinstance(e, str)] if isinstance(etapes, list) else [],
    }


PLAN_JUDGE_SYSTEM_PROMPT = (
    "Tu es le juge d'un agent qui accomplit des tâches web. On te donne un "
    "objectif, un plan (liste de sous-tâches avec critère de succès et "
    "outils prévus), et SI DISPONIBLE l'état ACTUEL de la page déjà visitée "
    "pour cette tâche (etat_actuel_de_la_page). Évalue s'il est réellement "
    "faisable et complet pour atteindre l'objectif. Si un état de page est "
    "fourni, base ton jugement sur ce qui existe RÉELLEMENT dessus (ex. ne "
    "reproche jamais l'absence d'une barre de recherche ou d'une "
    "fonctionnalité qui n'apparaît pas dans l'état fourni). Réponds "
    'UNIQUEMENT par un JSON de la forme {"faisable": true|false, "risques": '
    '["..."], "etapes_manquantes": ["..."]}, rien d\'autre : pas de texte '
    "avant/après, pas de balise <think>, pas de bloc de code."
)


async def _judge_plan(plan: list, objective: str, page_snapshot: Optional[str] = None) -> list:
    """
    Verdict du juge LLM (Itération 3, page_snapshot ajouté à l'Itération 4 —
    correctif d'ancrage, voir HISTORY.md) : liste des motifs de rejet (vide
    = faisable). Dégrade en FAIL-OPEN sur erreur LLM/JSON invalide (aucun
    motif renvoyé, pas de veto par défaut) — cohérent avec "jamais de
    boucle infinie" du brief : un juge indisponible ne doit jamais bloquer
    indéfiniment une tâche par ailleurs valide selon les heuristiques.
    """
    payload = json.dumps(
        {
            "objectif": objective,
            "plan": [
                {
                    "description": st.get("description", ""),
                    "critere_succes": st.get("success_criterion", ""),
                    "outils": st.get("tools", []),
                }
                for st in plan
            ],
            "etat_actuel_de_la_page": page_snapshot,
        },
        ensure_ascii=False,
    )
    try:
        response = await planner_llm.ainvoke([SystemMessage(content=PLAN_JUDGE_SYSTEM_PROMPT), HumanMessage(content=payload)])
        verdict = _validate_judge_json(response.content)
    except Exception:
        logger.warning("Juge de plan indisponible, aucun veto appliqué par défaut.", exc_info=True)
        return []
    if verdict["faisable"]:
        return []
    reasons = [f"juge : {r}" for r in verdict["risques"]] or ["juge : plan jugé non faisable"]
    if verdict["etapes_manquantes"]:
        reasons.append("juge : étapes manquantes — " + "; ".join(verdict["etapes_manquantes"]))
    return reasons


class VerificationValidationError(ValueError):
    """Levée par _validate_verification_json : verdict du vérificateur inexploitable."""


def _validate_verification_json(raw: str) -> dict:
    """
    Schéma validé PROGRAMMATIQUEMENT (Itération 2, même pipeline que
    _validate_plan_json) : retire <think>/fences, exige
    {"atteint": bool, "raison": str}. `raison` absente/non-str -> chaîne
    vide plutôt qu'une erreur (accessoire pour la visibilité, pas pour la
    décision elle-même) ; `atteint` doit être un booléen JSON réel (pas une
    chaîne "true"/"false") sans quoi le verdict est jugé inexploitable.
    """
    text = _strip_code_fence(_THINK_BLOCK_RE.sub("", raw or ""))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VerificationValidationError(f"JSON invalide : {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("atteint"), bool):
        raise VerificationValidationError("clé 'atteint' (bool) absente ou invalide")
    raison = data.get("raison")
    return {"atteint": data["atteint"], "raison": raison.strip() if isinstance(raison, str) else ""}


VERIFIER_SYSTEM_PROMPT = (
    "Tu es le vérificateur d'un agent. On te donne l'objectif global de la "
    "tâche (objectif_global), la description d'une sous-tâche, son critère "
    "de succès énoncé PAR AVANCE par le planificateur (critere_succes), le "
    "résultat brut de la dernière action (resultat), et si disponible "
    "l'état ACTUEL de la page (etat_actuel_de_la_page). Le critère de "
    "succès peut décrire une approche qui n'existe pas réellement sur "
    "cette page (ex. une barre de recherche supposée alors que le site "
    "n'a que de la pagination) — dans ce cas, juge la PROGRESSION RÉELLE "
    "vers l'objectif global et ce que montre effectivement la page "
    "actuelle, PAS une lecture littérale du critère si l'approche qu'il "
    "suppose n'existe pas. Réponds UNIQUEMENT par un JSON de la forme "
    '{"atteint": true|false, "raison": "..."}, rien d\'autre : pas de '
    "texte avant/après, pas de balise <think>, pas de bloc de code."
)


async def _fetch_verification_snapshot(objective: str) -> str:
    """
    Capture un browser_snapshot FRAIS au moment de la vérification —
    correctif d'ancrage trouvé pendant la sonde live de l'Itération 4 (voir
    HISTORY.md) : le résultat brut du dernier tool_call (ex. la
    confirmation d'un browser_click) est souvent TERSE, sans le contenu de
    la page qui en résulte. verify_action jugeait alors une sous-tâche
    "échouée" en se fiant uniquement à success_criterion — parfois lui-même
    mal ancré (ex. "utilise la barre de recherche" sur un site qui n'en a
    pas) — sans jamais voir que la page réelle montrait déjà une
    progression valide (ex. pagination). Best-effort : erreur mcp-client ->
    chaîne vide, le vérificateur juge alors avec les seules infos déjà
    disponibles (comportement identique à avant ce correctif) — jamais un
    blocage pour un souci de capture annexe, même philosophie que le reste
    de ce fichier.
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            result, _ = await _call_mcp_tool(client, "browser_snapshot", {})
        truncated = _truncate_browser_result(result, BROWSER_TOOL_OUTPUT_MAX_CHARS, objective)
        blocks = truncated.get("content", [])
        texts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(texts)
    except Exception:
        logger.warning("Capture de vérification (browser_snapshot) indisponible, jugement sans elle.", exc_info=True)
        return ""


async def _grounding_snapshot(state: dict, objective: str) -> Optional[str]:
    """
    Snapshot de la page courante pour ancrer une (re)planification/
    validation sur ce qui existe RÉELLEMENT (Itération 4, suite du
    correctif verify_action — voir HISTORY.md). `None` si aucune navigation
    n'a encore eu lieu pour cette tâche (state["current_page_url"], Phase
    1) : le TOUT PREMIER plan (plan_task) reste donc structurellement non
    ancré — aucune page n'existe encore à capturer à ce stade, et forcer
    une navigation exploratoire avant la planification soulèverait ses
    propres questions de tier/approbation (browser_navigate est
    TIER_SENSITIVE), hors périmètre ici. Les REPLANIFICATIONS
    (revise_plan/replan_task), elles, sont toujours déclenchées APRÈS
    qu'une navigation a eu lieu — c'est là que ce correctif s'applique.
    """
    if not state.get("current_page_url"):
        return None
    return await _fetch_verification_snapshot(objective) or None


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    tool_iterations: int
    approved: Optional[bool]
    # Tours auto-approuvés consécutifs depuis le dernier passage par
    # require_approval (voir AUTO_APPROVAL_STREAK_LIMIT plus haut).
    auto_approval_streak: int
    # Nombre de messages Open WebUI (rôles user/assistant) déjà intégrés à ce
    # thread — permet à app/main.py de ne soumettre que les nouveaux messages
    # à chaque tour plutôt que tout l'historique renvoyé par Open WebUI (qui
    # est déjà persisté ici via le checkpointer), et donc d'éviter de le
    # dupliquer dans "messages" à chaque tour.
    owui_message_count: int
    # État de la balise <think> (voir _think_state plus haut), reporté d'un
    # appel de call_llm à l'autre au sein d'un même tour utilisateur — requis
    # depuis AUTO_APPROVED_TOOLS, qui permet à call_llm de s'exécuter plusieurs
    # fois de suite sans pause d'approbation entre deux. Sans ce report, chaque
    # itération rouvrait sa propre balise <think>, et Open WebUI n'affiche en
    # bulle repliable que celle en tout début de message : les suivantes
    # apparaissaient en texte brut visible. Remis à False à chaque nouveau tour
    # (voir _resolve_run, app/main.py), comme tool_iterations.
    think_opened: bool
    think_closed: bool
    # Grants de session (Phase 3) : noms d'outils qu'un humain a approuvés
    # "pour la session" via require_approval (voir ce nœud plus bas) plutôt
    # qu'une fois seulement. Un outil dans cette liste est plafonné à
    # TIER_REVERSIBLE (auto + audit) pour le reste du thread, même s'il
    # serait normalement TIER_SENSITIVE (voir approval_policy.effective_tier).
    # Vit dans l'état du graphe, donc dans le checkpointer MemorySaver (en
    # mémoire uniquement) : un redémarrage du service perd les grants en même
    # temps que le reste du thread — comportement voulu, pas un bug (voir
    # README, section Supervision humaine).
    session_grants: list
    # Décision transitoire couplée à "approved" (voir require_approval) :
    # True si l'humain a répondu "approuver pour la session" plutôt que
    # "approuver" seul. Consommée puis remise à False dès que require_approval
    # a appliqué le grant, pour ne pas re-déclencher un grant à chaque reprise
    # ultérieure du thread.
    grant_session: bool
    # Compteur de retries pour le filet de sécurité "réponse vide" (voir
    # MAX_EMPTY_ANSWER_RETRIES plus haut) — budget cumulé pour toute la
    # tâche, comme tool_iterations, jamais remis à zéro entre deux retries.
    empty_answer_retries: int
    # Signal explicite (pas déduit de la forme des messages, trop fragile —
    # un tour LLM normal qui a analysé une image via vision produit aussi un
    # AIMessage juste après un message image) : True uniquement quand le
    # dernier message vient de run_slash_command_direct ET portait une
    # image, pour que main.py sache reconstruire l'affichage de l'image pour
    # CE tour (_render_visible_answer) sans la persister en base64 dans le
    # message assistant lui-même. call_llm le remet à False à chaque appel :
    # c'est le seul autre nœud qui termine un tour sur un AIMessage visible,
    # donc la seule remise à zéro nécessaire pour que ce signal reste correct
    # quelle que soit la façon dont ce tour se termine.
    slash_command_image_shown: bool
    # Garde-fou fabrication d'URL (Phase 1, voir _check_navigate_url) :
    # ensemble des URL "vues" pour cette tâche — cible de départ (racines du
    # périmètre, extraites du 1er message humain), navigations déjà
    # exécutées, et liens observés dans le contenu renvoyé par un outil
    # browser_* (snapshot/DOM). Remis à zéro à chaque nouveau tour utilisateur
    # (voir run_input, app/main.py), comme tool_iterations — le périmètre est
    # celui de LA TÂCHE en cours, pas de toute la conversation.
    observed_urls: list
    # URL de la page actuellement chargée dans le navigateur (dernière valeur
    # "Page URL: ..." vue dans un résultat d'outil browser_*), nécessaire pour
    # résoudre les liens RELATIFS (ex. "/catalog/product-14.html") en URL
    # absolues avant de les ajouter à observed_urls.
    current_page_url: Optional[str]
    # Liens de la DERNIÈRE page vue (remplacés, pas accumulés, contrairement
    # à observed_urls) : utilisés pour orienter le modèle vers de vrais
    # liens quand une navigation fabriquée est refusée (voir
    # _execute_tool_calls) — "voici où tu es réellement", pas tout
    # l'historique de navigation qui serait moins actionnable.
    current_page_links: list
    # Compteur de tentatives de navigation vers une URL non observée,
    # bloquées AVANT exécution (voir _check_navigate_url) — métrique Phase 1,
    # pas juste un frein silencieux.
    fabricated_navigation_attempts: int
    # Plan explicite de la tâche (Itération 1, Phase 1 « cœur cognitif » —
    # voir docs/briefs/phase-1-coeur-cognitif.md et plan_task plus bas) :
    # liste de {description, success_criterion, status, attempts, result}.
    # status ∈ {"a_faire", "en_cours", "fait", "echoue"} (string libre, pas
    # d'enum dédié — cohérent avec failure_cause dans le harnais de tests).
    # Calculé UNE FOIS par plan_task au tout début d'une tâche (liste vide ->
    # le planificateur tourne ; non vide -> passthrough, jamais reconstruit
    # au sein d'une même tâche). Remis à [] à chaque NOUVEAU message
    # utilisateur top-level (voir run_input, app/main.py), comme
    # observed_urls. Aucune validation/tier/vérification post-action
    # branchée dessus pour l'instant (Itérations 2/3 à venir) : structure et
    # visibilité seules à l'Itération 1 ; vérification post-action/budget
    # d'échec branchés dessus depuis l'Itération 2 (voir verify_action,
    # replan_task, report_failure plus bas). No-op tant que PLANNER_ENABLED
    # est désactivé (défaut) : reste alors toujours [].
    plan: list
    # Nombre de replanifications déjà effectuées pour CETTE tâche (Itération
    # 2, voir replan_task/route_after_verification) — budget cumulé, comme
    # tool_iterations, plafonné par REPLAN_BUDGET. Remis à 0 à chaque
    # nouveau message utilisateur top-level (voir run_input, app/main.py).
    replan_count: int
    # Pipeline de validation du plan (Itération 3, voir validate_plan/
    # revise_plan/require_plan_approval plus bas). plan_validation_reasons :
    # motifs du DERNIER rejet (heuristiques et/ou juge), [] si le plan
    # courant est valide (ou pas encore évalué). plan_validation_cycles :
    # nombre de rejets subis pour CETTE tâche (pas par plan proposé — un
    # budget partagé entre planification initiale et replanifications,
    # voir PLAN_VALIDATION_CYCLES_MAX), au-delà escalade humaine plutôt que
    # de reboucler indéfiniment sur le planificateur. Les deux remis à
    # zéro/vide à chaque nouveau message utilisateur top-level (voir
    # run_input, app/main.py).
    plan_validation_reasons: list
    plan_validation_cycles: int
    # Approbation du plan (Itération 3) : miroir de approved/grant_session
    # (require_approval) mais pour le PLAN entier plutôt qu'un tool_call —
    # voir require_plan_approval. plan_grant : persisté (contrairement à
    # plan_grant_session, transitoire) — un plan-level grant accordé une
    # fois évite la pause sur une replanification ultérieure DANS LA MÊME
    # TÂCHE tant que le nouveau tier reste TIER_REVERSIBLE ou moins, jamais
    # pour TIER_SENSITIVE (même philosophie que NEVER_GRANTABLE_TOOLS,
    # approval_policy.py).
    plan_approved: Optional[bool]
    plan_grant_session: bool
    plan_grant: bool


# Plafond de tokens par TOUR (un seul appel LLM), pas pour la conversation
# entière : sans lui, une dérive en boucle de répétition (observée en usage
# réel avec un modèle très quantisé — voir README) génère jusqu'à saturer
# tout le contexte avant de s'arrêter (des dizaines de secondes, des milliers
# de tokens), sans jamais produire de tool_calls ni déclencher nos propres
# garde-fous (MAX_TOOL_ITERATIONS/AUTO_APPROVAL_STREAK_LIMIT), qui ne comptent
# que des itérations d'outils, pas la longueur d'une génération.
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "2048"))

llm = ChatOpenAI(
    base_url=LLM_BASE_URL,
    api_key="not-needed",       # tabbyapi (disable_auth: true)/llama-server/Ollama ne vérifient pas la clé par défaut
    model="agent-llm",          # doit matcher model_name dans services/tabbyapi/config.yml
    temperature=0.2,
    max_tokens=LLM_MAX_TOKENS,
)

# Bug découvert en conditions réelles en vérifiant la campagne live de
# l'Itération 3 (voir HISTORY.md) : les appels LLM auxiliaires (plan_task/
# revise_plan/verify_action/_judge_plan) utilisaient `llm` ci-dessus, plafonné
# à LLM_MAX_TOKENS (2048, pensé pour le tour conversationnel principal).
# Qwen3.6/TabbyAPI raisonne dans un champ reasoning_content SÉPARÉ de
# content avant de répondre (confirmé par un appel direct à TabbyAPI hors
# streaming) ; ce raisonnement, souvent long, consommait à lui seul tout le
# budget, tronquant `content` à vide ou au milieu du JSON
# (finish_reason="length") — chaque validateur retombait alors
# systématiquement sur son repli d'erreur, jamais sur une vraie évaluation.
# `/no_think` en préfixe de prompt (mécanisme ADAPTIVE_THINKING existant)
# ne supprime PAS le raisonnement sur ce backend (vérifié par le même appel
# direct) — solution retenue : un budget de tokens plus généreux, dédié à
# ces appels structurés, séparé du budget de la boucle principale (dont la
# petite valeur reste un filet de sécurité voulu contre les dérives de
# répétition, voir LLM_MAX_TOKENS).
PLANNER_MAX_TOKENS = int(os.environ.get("PLANNER_MAX_TOKENS", "8192"))
planner_llm = ChatOpenAI(
    base_url=LLM_BASE_URL,
    api_key="not-needed",
    model="agent-llm",
    temperature=0.2,
    max_tokens=PLANNER_MAX_TOKENS,
)

# Schéma des outils MCP (terminal/filesystem/git/browser/desktop-GhostDesk),
# récupéré depuis mcp-client et mis en cache pour la durée du process. Sans
# ce bind_tools, le LLM n'a aucune connaissance de l'existence de ces outils
# et ne peut donc jamais produire de tool_calls, quel que soit le modèle
# servi — has_tool_calls()/require_approval() restent alors du code mort.
_tools_schema_cache: Optional[list] = None


async def _get_tools_schema() -> list:
    """Remplit/retourne _tools_schema_cache — factorisé hors de _get_bound_llm
    pour être aussi utilisable par _route_entry (validation du nom d'outil
    d'une commande slash) sans requête HTTP supplémentaire une fois en cache."""
    global _tools_schema_cache
    if _tools_schema_cache is None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{MCP_CLIENT_URL}/tools/schema")
                resp.raise_for_status()
                _tools_schema_cache = resp.json().get("tools", [])
        except (httpx.HTTPError, ValueError):
            # mcp-client injoignable ou réponse invalide : dégrade sans outils
            # plutôt que de faire échouer toute la conversation.
            _tools_schema_cache = []
    return _tools_schema_cache


async def _get_bound_llm() -> ChatOpenAI:
    schema = await _get_tools_schema()
    return llm.bind_tools(schema) if schema else llm


async def retrieve_context(state: AgentState) -> dict:
    last_user_msg = next(
        (m.content for m in reversed(state["messages"]) if m.type == "human"), ""
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{CONTEXT_MANAGER_URL}/retrieve", json={"query": last_user_msg, "top_k": 5}
            )
            resp.raise_for_status()
            snippets = resp.json().get("results", [])
    except httpx.HTTPError:
        snippets = []

    if not snippets:
        return {"messages": []}

    context_text = "\n".join(f"- {s}" for s in snippets)
    return {"messages": [{"role": "system", "content": f"Contexte pertinent récupéré :\n{context_text}"}]}


async def select_skill(state: AgentState) -> dict:
    last_user_msg = next(
        (m.content for m in reversed(state["messages"]) if m.type == "human"), ""
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SKILL_MANAGER_URL}/match", json={"query": last_user_msg}
            )
            resp.raise_for_status()
            skill = resp.json().get("skill")
    except httpx.HTTPError:
        skill = None

    if not skill:
        return {"messages": []}

    return {"messages": [{"role": "system", "content": f"Skill activée : {skill['name']}\n{skill['content']}"}]}


async def _available_tools_hint() -> str:
    """
    Liste réelle des outils MCP disponibles (découvert en conditions
    réelles pendant la campagne live de l'Itération 3, voir HISTORY.md) :
    sans elle, le planificateur invente des noms d'outils plausibles mais
    inexistants (ex. "web_browser", "search") — systématiquement rejetés
    par les heuristiques (outils référencés existants,
    app/plan_validation.py), aucun plan ne passerait jamais la validation.
    Ajoutée au message UTILISATEUR (pas au system prompt, figé lui) pour
    rester à jour si le schéma d'outils change entre deux tâches. Utilisée
    par plan_task/revise_plan/replan_task.
    """
    schema = await _get_tools_schema()
    names = sorted({t.get("function", {}).get("name") for t in schema} - {None})
    if not names:
        return ""
    return (
        "\n\nOutils réellement disponibles (utilise UNIQUEMENT ces noms exacts "
        'dans "outils", liste vide si aucun ne s\'applique) : ' + ", ".join(names)
    )


async def plan_task(state: AgentState) -> dict:
    """
    Nœud planificateur (Itération 1, Phase 1 « cœur cognitif »). No-op
    (`{"messages": []}`) si PLANNER_ENABLED est désactivé (défaut), si un
    plan existe déjà pour cette tâche (calculé une seule fois, jamais
    reconstruit au sein d'une même tâche — voir AgentState.plan) ou s'il n'y
    a aucun message humain à planifier.

    Appel LLM séparé de call_llm : `llm` brut (jamais `bound_llm`), le
    planificateur ne doit jamais émettre de tool_calls, seulement du JSON.

    Dégrade TOUJOURS sur un plan à sous-tâche unique plutôt que de bloquer
    la tâche pour un souci de planification annexe (transport HTTP, réponse
    invalide) — capture large volontaire (PlanValidationError ou n'importe
    quelle erreur du client OpenAI/httpx), même esprit que la dégradation
    httpx.HTTPError de retrieve_context/select_skill ci-dessus, élargie ici
    car l'échec peut aussi venir de la validation JSON, pas seulement du
    transport.
    """
    if not PLANNER_ENABLED or state.get("plan"):
        return {"messages": []}
    first_human = next((m for m in state["messages"] if getattr(m, "type", None) == "human"), None)
    objective = first_human.content if first_human and isinstance(first_human.content, str) else ""
    if not objective:
        return {"messages": []}

    try:
        tools_hint = await _available_tools_hint()
        response = await planner_llm.ainvoke(
            [SystemMessage(content=PLANNER_SYSTEM_PROMPT), HumanMessage(content=objective + tools_hint)]
        )
        subtasks = _validate_plan_json(response.content)
    except Exception:
        logger.warning("Planification échouée, repli sur un plan à sous-tâche unique.", exc_info=True)
        subtasks = [{"description": objective, "success_criterion": "objectif de la tâche atteint", "tools": []}]

    plan = [{**st, "status": "a_faire", "attempts": 0, "result": None} for st in subtasks]
    if plan:
        plan[0]["status"] = "en_cours"
    logger.info("Plan initial (%d sous-tâche(s)) : %s", len(plan), plan)
    return {"plan": plan}


def _plan_tier(plan: list) -> str:
    """
    Tier du plan = pire tier parmi TOUS les outils déclarés par ses
    sous-tâches (Itération 3) — approval_policy.tool_tier(), qui retombe
    déjà sur TIER_SENSITIVE pour un outil inconnu (défaut existant "outil
    inconnu = toujours sensible", cohérent ici). Aucun outil déclaré nulle
    part -> TIER_READ (rien à approuver en amont).
    """
    tiers = {approval_policy.tool_tier(tool) for subtask in plan for tool in subtask.get("tools", [])}
    if approval_policy.TIER_SENSITIVE in tiers:
        return approval_policy.TIER_SENSITIVE
    if approval_policy.TIER_REVERSIBLE in tiers:
        return approval_policy.TIER_REVERSIBLE
    return approval_policy.TIER_READ


async def validate_plan(state: AgentState) -> dict:
    """
    Pipeline de validation du plan (Itération 3, Phase 1 « cœur cognitif »).
    No-op (`{"messages": []}`) si PLAN_VALIDATION_ENABLED désactivé
    (défaut) ou si `state["plan"]` est vide — comportement identique à
    avant cette itération. Sinon : heuristiques programmatiques
    (app/plan_validation.py, gratuites) puis, UNIQUEMENT si elles passent
    ET que PLAN_JUDGE_ENABLED, juge LLM (coûteux — clause de retrait, voir
    HISTORY.md). Rejet (heuristiques OU juge) -> plan_validation_cycles
    incrémenté, motifs renvoyés pour route_after_validation.
    """
    if not PLAN_VALIDATION_ENABLED:
        return {"messages": []}
    plan = state.get("plan") or []
    if not plan:
        return {"messages": []}

    schema = await _get_tools_schema()
    known_tools = {t.get("function", {}).get("name") for t in schema}
    known_tools.discard(None)
    task_scope = _task_scope_urls(state["messages"])
    reasons = plan_validation.validate_plan_heuristics(plan, known_tools=known_tools, task_scope_urls=task_scope)

    if not reasons and PLAN_JUDGE_ENABLED:
        first_human = next((m for m in state["messages"] if getattr(m, "type", None) == "human"), None)
        objective = first_human.content if first_human and isinstance(first_human.content, str) else ""
        page_snapshot = await _grounding_snapshot(state, objective)
        reasons = await _judge_plan(plan, objective, page_snapshot)

    if reasons:
        cycles = state.get("plan_validation_cycles", 0) + 1
        logger.warning("Plan rejeté par la validation (cycle %d) : %s", cycles, reasons)
        # plan_approved réarmé à None ICI (pas dans require_plan_approval,
        # voir son commentaire) : que ce rejet mène à une révision ou à une
        # escalade humaine, toute décision précédente sur un plan ANTÉRIEUR
        # ne doit jamais être réutilisée pour celui-ci.
        return {"plan_validation_reasons": reasons, "plan_validation_cycles": cycles, "plan_approved": None}

    logger.info("Plan validé (%d sous-tâche(s)).", len(plan))
    return {"plan_validation_reasons": [], "plan_approved": None}


def route_after_validation(state: AgentState) -> str:
    """
    Routage après validate_plan. PLAN_VALIDATION_ENABLED désactivé ->
    "call_llm" (flux identique à avant cette itération). Rejeté ->
    "revise_plan" tant que PLAN_VALIDATION_CYCLES_MAX n'est pas dépassé,
    sinon "require_plan_approval" (escalade humaine, motifs affichés).
    Accepté -> "call_llm" si TIER_READ ou si TIER_REVERSIBLE et un grant de
    plan est déjà accordé pour cette tâche (plan_grant, jamais pour
    TIER_SENSITIVE), sinon "require_plan_approval" (approbation normale).
    """
    if not PLAN_VALIDATION_ENABLED:
        return "call_llm"
    reasons = state.get("plan_validation_reasons") or []
    if reasons:
        cycles = state.get("plan_validation_cycles", 0)
        return "revise_plan" if cycles <= PLAN_VALIDATION_CYCLES_MAX else "require_plan_approval"
    tier = _plan_tier(state.get("plan") or [])
    if tier == approval_policy.TIER_READ:
        return "call_llm"
    if tier == approval_policy.TIER_REVERSIBLE and state.get("plan_grant"):
        return "call_llm"
    return "require_plan_approval"


async def revise_plan(state: AgentState) -> dict:
    """
    Révision du plan suite à un rejet du pipeline de validation (Itération
    3). Distinct de replan_task (Itération 2, déclenché par un ÉCHEC
    D'EXÉCUTION d'une sous-tâche) : ici, rien n'a encore été exécuté — le
    plan lui-même est jugé structurellement/sémantiquement insuffisant
    AVANT le premier tour. Régénère le plan ENTIER (aucune sous-tâche
    "fait" à préserver) avec les motifs de rejet en contexte. Même repli
    que plan_task sur échec de génération (plan à sous-tâche unique).
    """
    reasons = state.get("plan_validation_reasons") or []
    first_human = next((m for m in state["messages"] if getattr(m, "type", None) == "human"), None)
    objective = first_human.content if first_human and isinstance(first_human.content, str) else ""
    motifs = "\n".join(f"- {r}" for r in reasons) or "(motif non précisé)"
    page_snapshot = await _grounding_snapshot(state, objective)
    snapshot_hint = (
        f"\nÉtat actuel de la page (ce qui est RÉELLEMENT visible maintenant, base-toi dessus) :\n{page_snapshot}\n"
        if page_snapshot
        else ""
    )
    context = (
        f"Objectif original : {objective}\n"
        f"Ta précédente proposition de plan a été rejetée pour les raisons suivantes :\n{motifs}\n"
        f"{snapshot_hint}"
        "Propose un NOUVEAU plan qui corrige ces problèmes."
    )
    try:
        tools_hint = await _available_tools_hint()
        response = await planner_llm.ainvoke(
            [SystemMessage(content=PLANNER_SYSTEM_PROMPT), HumanMessage(content=context + tools_hint)]
        )
        subtasks = _validate_plan_json(response.content)
    except Exception:
        logger.warning("Révision du plan échouée, repli sur un plan à sous-tâche unique.", exc_info=True)
        subtasks = [{"description": objective, "success_criterion": "objectif de la tâche atteint", "tools": []}]

    plan = [{**st, "status": "a_faire", "attempts": 0, "result": None} for st in subtasks]
    if plan:
        plan[0]["status"] = "en_cours"
    logger.info("Plan révisé (%d sous-tâche(s), cycle de validation) : %s", len(plan), plan)
    return {"plan": plan}


async def require_plan_approval(state: AgentState) -> dict:
    """
    Approbation humaine du PLAN (Itération 3) : miroir de require_approval
    mais pour le plan entier plutôt qu'un tool_call — pause (NodeInterrupt)
    tant que plan_approved est None. Reste NON FUSIONNABLE avec
    l'approbation individuelle d'un outil TIER_SENSITIVE à l'exécution :
    ce nœud est un gate ADDITIONNEL en amont, require_approval/
    _execute_tool_calls restent inchangés et s'appliquent quand même.
    """
    if state.get("plan_approved") is None:
        raise NodeInterrupt("Approbation humaine du plan requise avant exécution.")
    # NE PAS remettre plan_approved à None ici : route_after_plan_approval
    # (juste après) doit encore pouvoir lire la décision (True/False) telle
    # que ce nœud vient de la recevoir — même piège déjà évité par
    # require_approval, qui laisse "approved" intact pour route_after_approval
    # et ne le réarme qu'ailleurs (_execute_tool_calls, pour le tour
    # suivant). Ici, c'est validate_plan qui réarme plan_approved à None à
    # chaque nouveau plan proposé (voir ce nœud).
    updates = {"plan_grant_session": False}
    if state.get("plan_grant_session"):
        updates["plan_grant"] = True
    return updates


def route_after_plan_approval(state: AgentState) -> str:
    return "call_llm" if state["plan_approved"] else "reject_plan"


async def reject_plan(state: AgentState) -> dict:
    """Miroir de reject_tools, côté plan : l'humain a refusé le plan proposé, la tâche s'arrête ici."""
    return {"messages": [{"role": "assistant", "content": "Plan refusé par l'utilisateur — tâche non exécutée."}]}


def _is_image_message(message) -> bool:
    return (
        getattr(message, "type", None) == "human"
        and isinstance(message.content, list)
        and any(isinstance(b, dict) and b.get("type") == "image_url" for b in message.content)
    )


_CONTEXT_BLOCK_SKELETON = (
    ("System prompt", "system"),
    ("Skills", "skills"),
    ("Schéma d'outils", "tools_schema"),
    ("Historique (texte)", "history_text"),
    ("Images", "images"),
)


def describe_context(messages: list, pending_text: Optional[str] = None) -> list[dict]:
    """
    Décomposition approximative (voir estimate_tokens) du contexte tel qu'il
    serait construit pour un appel LLM (voir call_llm), à l'usage de POST
    /context (app/main.py) et donc du dashboard d'observabilité
    (services/dashboard) — jamais un vrai appel au LLM, et le schéma d'outils
    est lu tel quel depuis _tools_schema_cache (jamais recalculé via
    _get_bound_llm, qui ferait un appel HTTP à mcp-client : /context doit
    rester strictement lecture seule, sans effet de bord, comme /pending).

    `messages` vide (thread inconnu du checkpointer) -> tous les blocs à
    zéro plutôt que d'inclure quand même le system prompt transitoire
    (GROUNDING_DIRECTIVE) : rien n'a encore été composé pour ce thread.
    """
    if not messages:
        return [
            {"label": label, "kind": kind, "est_tokens": 0, "count": 0}
            for label, kind in _CONTEXT_BLOCK_SKELETON
        ]

    system_parts = [GROUNDING_DIRECTIVE, DOWNLOAD_DIRECTIVE]
    skills_parts = []
    history_parts = []
    image_count = 0

    for message in messages:
        content = message.content
        if getattr(message, "type", None) == "system":
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            if text.startswith("Skill activée :"):
                skills_parts.append(text)
            else:
                system_parts.append(text)
        elif _is_image_message(message):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "image_url":
                    image_count += 1
                elif block.get("type") == "text":
                    history_parts.append(block.get("text", ""))
        else:
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            history_parts.append(text)

    blocks = [
        {
            "label": "System prompt",
            "kind": "system",
            "est_tokens": estimate_tokens("\n".join(system_parts)),
            "count": len(system_parts),
        },
        {
            "label": "Skills",
            "kind": "skills",
            "est_tokens": estimate_tokens("\n".join(skills_parts)),
            "count": len(skills_parts),
        },
        {
            "label": "Schéma d'outils",
            "kind": "tools_schema",
            "est_tokens": estimate_tokens(json.dumps(_tools_schema_cache or [], ensure_ascii=False)),
            "count": len(_tools_schema_cache or []),
        },
        {
            "label": "Historique (texte)",
            "kind": "history_text",
            "est_tokens": estimate_tokens("\n".join(history_parts)),
            "count": len(history_parts),
        },
        {
            "label": "Images",
            "kind": "images",
            "est_tokens": image_count * IMAGE_TOKEN_ESTIMATE,
            "count": image_count,
        },
    ]
    if pending_text:
        blocks.append(
            {
                "label": "Approbation en attente",
                "kind": "pending",
                "est_tokens": estimate_tokens(pending_text),
                "count": 1,
            }
        )
    return blocks


def _apply_image_retention(messages: list) -> list:
    """
    Ne garde que les MAX_IMAGES_IN_CONTEXT derniers messages image (voir
    _is_image_message) dans la liste envoyée au LLM ; les précédents sont
    remplacés par un message texte indicatif. Retourne une NOUVELLE liste
    (jamais de mutation en place des messages d'origine, qui sont les mêmes
    objets Python que ceux persistés par le checkpointer) — c'est ce qui
    garantit que ce filtrage reste local à cet appel, sans jamais toucher à
    l'état du graphe.
    """
    image_indices = [i for i, m in enumerate(messages) if _is_image_message(m)]
    cutoff = len(image_indices) - max(MAX_IMAGES_IN_CONTEXT, 0)
    if cutoff <= 0:
        return messages

    filtered = list(messages)
    for i in image_indices[:cutoff]:
        filtered[i] = HumanMessage(content=IMAGE_RETENTION_PLACEHOLDER)
    return filtered


def _previous_turn_tool_calls(messages: list) -> Optional[list]:
    """Dernier message AI avec tool_calls dans l'historique — le tour qui a mené à cet appel de call_llm."""
    for message in reversed(messages):
        if getattr(message, "type", None) == "ai" and getattr(message, "tool_calls", None):
            return message.tool_calls
    return None


def _previous_turn_tool_results(messages: list) -> list[str]:
    """
    Contenus des ToolMessage produits par le dernier tour de tool_calls
    (Itération 2, voir verify_action plus bas) : repère la limite via le
    dernier AIMessage avec tool_calls (même idiome que
    _previous_turn_tool_calls), puis ne garde QUE les messages "tool" après
    cette limite — ignore les messages image "user" que _split_image_blocks
    peut intercaler (_execute_tool_calls) : le vérificateur ne raisonne que
    sur du texte.
    """
    boundary = None
    for i in range(len(messages) - 1, -1, -1):
        if getattr(messages[i], "type", None) == "ai" and getattr(messages[i], "tool_calls", None):
            boundary = i
            break
    if boundary is None:
        return []
    results = []
    for message in messages[boundary + 1 :]:
        if getattr(message, "type", None) == "tool":
            content = message.content
            results.append(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False))
    return results


def _apply_adaptive_thinking(messages: list, session_grants) -> list:
    """
    Ajoute un system prompt transitoire "/no_think" (jamais persisté dans
    l'état du graphe, voir _apply_image_retention pour le même principe)
    quand ADAPTIVE_THINKING est activé ET que le tour précédent était
    entièrement auto-approuvé (même politique par tiers que has_tool_calls) —
    typiquement une boucle perception-action GhostDesk (capture -> clic ->
    capture) où le raisonnement étendu de Qwen3.6 coûte plus qu'il n'apporte.
    Pas d'injection sur le tout premier tour d'une tâche (aucun tool_calls
    précédent) ni dès qu'un outil sensible était en jeu : le raisonnement y
    a le plus de valeur.
    """
    if not ADAPTIVE_THINKING:
        return messages
    previous_tool_calls = _previous_turn_tool_calls(messages)
    if not previous_tool_calls:
        return messages
    all_auto_approved = all(
        approval_policy.is_auto_approved(tc["name"], tc.get("args"), session_grants)
        for tc in previous_tool_calls
    )
    if not all_auto_approved:
        return messages
    # Fusionné dans le message système de tête s'il y en a un (cas réel :
    # GROUNDING_DIRECTIVE, ajouté par call_llm juste avant cet appel), sinon
    # ajouté en position 0 — jamais en fin de liste : certains backends
    # (TabbyAPI/ExLlamaV3, template Jinja strict de Qwen3.6) rejettent
    # explicitement un second message système ou un message système non en
    # tête ("TemplateError: System message must be at the beginning") —
    # llama-server/Ollama tolèrent les deux formes, donc ce bug restait
    # invisible avant la migration vers TabbyAPI.
    if messages and isinstance(messages[0], SystemMessage):
        head, *rest = messages
        merged_head = SystemMessage(content=f"{head.content}\n{NO_THINK_DIRECTIVE}")
        return [merged_head] + rest
    return [SystemMessage(content=NO_THINK_DIRECTIVE)] + messages


async def call_llm(state: AgentState, config: dict) -> dict:
    bound_llm = await _get_bound_llm()
    messages_for_llm = [
        SystemMessage(content=f"{GROUNDING_DIRECTIVE}\n{DOWNLOAD_DIRECTIVE}")
    ] + state["messages"]
    messages_for_llm = _apply_image_retention(messages_for_llm)
    messages_for_llm = _apply_adaptive_thinking(messages_for_llm, state.get("session_grants") or [])
    # Repris tel quel depuis l'appel précédent au sein de ce tour (voir
    # AgentState.think_opened/think_closed) plutôt que remis à False, pour ne
    # produire qu'une seule balise <think> continue même si call_llm boucle
    # plusieurs fois via AUTO_APPROVED_TOOLS.
    token = _think_state.set(
        {"opened": state.get("think_opened", False), "closed": state.get("think_closed", False)}
    )
    try:
        merged = None
        async for chunk in bound_llm.astream(messages_for_llm):
            merged = chunk if merged is None else merged + chunk
    finally:
        think = _think_state.get()
        _think_state.reset(token)

    # Ne force la fermeture ici que si ce tour n'ira pas relancer call_llm
    # (pas de tool_calls) : sinon on couperait prématurément un <think>
    # censé continuer sur la prochaine itération de la boucle d'outils
    # auto-approuvés. Le cas "tool_calls + pause d'approbation humaine" est
    # géré séparément côté flux streamé (voir needs_closing_tag, app/main.py).
    if think["opened"] and not think["closed"] and not getattr(merged, "tool_calls", None):
        merged.content += "</think>"
        think["closed"] = True

    # Filet de sécurité (voir MAX_EMPTY_ANSWER_RETRIES plus haut pour la
    # cause racine) : le modèle a parfois écrit son appel d'outil en prose
    # au lieu de le faire reconnaître par la grammaire du serveur. Avant de
    # compter ce tour comme un échec (voir has_tool_calls), on tente de
    # récupérer l'intention plutôt que de perdre le tour.
    if not getattr(merged, "tool_calls", None):
        fallback = _extract_fallback_tool_call(merged.content)
        if fallback:
            logger.warning(
                "Tool call de secours extrait d'une réponse non structurée "
                "(outil=%s, args=%s) : le modèle a écrit son appel en prose "
                "au lieu d'émettre un tool_calls OpenAI reconnu par le serveur.",
                fallback["name"],
                fallback["args"],
            )
            merged.tool_calls = [fallback]

    # Observabilité (Phase 1d-révisée, voir HISTORY.md "correctif
    # extraction" -> "OBSERVABILITÉ") : persiste CE tour du modèle
    # (raisonnement <think> + texte + tool_calls éventuels), qu'il soit
    # ensuite auto-approuvé, soumis à approbation ou refusé — contrairement
    # au journal des tool_calls (log_tool_call), volontairement partiel par
    # tier, cette trace-ci n'a pas besoin d'être sélective : c'est le
    # raisonnement de l'agent, jamais un effet de bord à filtrer.
    thread_id = config.get("configurable", {}).get("thread_id", "")
    audit_log.log_message(
        thread_id,
        "assistant",
        {"content": merged.content, "tool_calls": getattr(merged, "tool_calls", None)},
    )

    return {
        "messages": [merged],
        "think_opened": think["opened"],
        "think_closed": think["closed"],
        # Remis à False à chaque appel : c'est le seul autre nœud qui
        # termine un tour sur un AIMessage visible (voir
        # AgentState.slash_command_image_shown) — sans cette remise à zéro,
        # un tour LLM normal qui suit une image (ex. vision sur screen_shot
        # décidé par le modèle) réutiliserait à tort la reconstruction
        # d'image de main.py, dupliquant l'image dans sa propre réponse déjà
        # correcte.
        "slash_command_image_shown": False,
    }


def has_tool_calls(state: AgentState) -> str:
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None)
    if not tool_calls:
        # Filet de sécurité "réponse vide" (voir MAX_EMPTY_ANSWER_RETRIES) :
        # aucun tool_calls (même après tentative d'extraction de secours
        # dans call_llm) ET rien de visible hors <think> -> reboucle sur
        # call_llm plutôt que d'abandonner immédiatement, tant que le budget
        # de retries n'est pas épuisé.
        if not has_visible_answer(last.content) and state.get("empty_answer_retries", 0) < MAX_EMPTY_ANSWER_RETRIES:
            return "retry_empty_answer"
        return "end"
    if state["tool_iterations"] >= MAX_TOOL_ITERATIONS:
        return "end"
    grants = state.get("session_grants") or []
    all_auto_approved = all(
        approval_policy.is_auto_approved(tc["name"], tc.get("args"), grants) for tc in tool_calls
    )
    # Le garde-fou clavier virtuel (voir AUTO_APPROVAL_STREAK_LIMIT) : même un
    # tour entièrement auto-approuvé repasse par require_approval une fois le
    # plafond de tours consécutifs sans supervision humaine atteint.
    if all_auto_approved and state.get("auto_approval_streak", 0) < AUTO_APPROVAL_STREAK_LIMIT:
        return "auto_call_tools"
    return "call_tools"


async def retry_empty_answer(state: AgentState) -> dict:
    """
    Point de reboucle du filet de sécurité "réponse vide" (voir
    MAX_EMPTY_ANSWER_RETRIES). Remet aussi think_opened/think_closed à False
    pour que la nouvelle tentative reparte sur une balise <think> fraîche —
    sans ça, le raisonnement du retry s'afficherait en texte brut (déjà
    "opened" selon l'état persisté par la tentative ratée), invisible en
    dehors d'une bulle repliable.
    """
    return {
        "empty_answer_retries": state.get("empty_answer_retries", 0) + 1,
        "think_opened": False,
        "think_closed": False,
    }


async def require_approval(state: AgentState) -> dict:
    """Point de pause : bloque tant qu'un humain n'a pas approuvé/refusé (voir app/main.py)."""
    if state.get("approved") is None:
        raise NodeInterrupt("Approbation humaine requise avant exécution d'outil.")
    # Passage réel par un humain : réarme le budget de tours auto-approuvés
    # consécutifs (voir AUTO_APPROVAL_STREAK_LIMIT).
    updates = {"messages": [], "auto_approval_streak": 0, "grant_session": False}
    # "approuver pour la session" (Phase 3) : les outils du tour en attente
    # rejoignent session_grants, plafonnés à TIER_REVERSIBLE (auto + audit)
    # pour le reste du thread — voir approval_policy.effective_tier() et
    # AgentState.session_grants. Le tour lui-même reste soumis à CETTE
    # approbation (un grant ne s'applique qu'à partir du PROCHAIN appel du
    # même outil, pas rétroactivement à celui qui l'a demandé).
    if state.get("grant_session"):
        last = state["messages"][-1]
        granted_names = {tc["name"] for tc in last.tool_calls}
        updates["session_grants"] = list(set(state.get("session_grants") or []) | granted_names)
    return updates


def route_after_approval(state: AgentState) -> str:
    return "call_tools" if state["approved"] else "reject_tools"


def _to_png_data_uri(data_b64: str, mime_type: str) -> str:
    """
    Réencode systématiquement en PNG avant de transmettre au LLM. Le décodeur
    d'image d'Ollama (mtmd, côté llama.cpp) échoue explicitement sur le WebP
    ("Failed to load image or audio file") — or c'est le format par défaut de
    l'outil screen_shot de GhostDesk. Convertir ici plutôt que de compter sur
    le modèle pour systématiquement demander format="png" à chaque appel.
    Chemin par défaut (IMAGE_FORMAT_PASSTHROUGH non activé) — voir
    _to_image_data_uri pour le chemin WebP direct.
    """
    if mime_type == "image/png":
        return f"data:image/png;base64,{data_b64}"
    raw = base64.b64decode(data_b64)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


def _to_image_data_uri(data_b64: str, mime_type: str) -> str:
    """
    IMAGE_FORMAT_PASSTHROUGH=webp : transmet le WebP brut de screen_shot tel
    quel (data URI directe, aucun décodage/réencodage Pillow), en s'appuyant
    sur le décodage WebP natif du fork llama.cpp servi par le backend
    alternatif llama-server (voir README, section Backend d'inférence) —
    évite le coût CPU de la reconversion PNG à chaque capture. Défaut
    (variable absente/différente de "webp", cas de TabbyAPI comme
    d'Ollama) : conversion PNG systématique via _to_png_data_uri.
    """
    if IMAGE_FORMAT_PASSTHROUGH:
        return f"data:{mime_type};base64,{data_b64}"
    return _to_png_data_uri(data_b64, mime_type)


def _split_image_blocks(result: dict) -> tuple[dict, list[dict]]:
    """
    Sépare les blocs image (format MCP : {"type": "image", "data": <base64>,
    "mimeType": ...}) du reste du résultat d'outil. Un ToolMessage (role
    "tool") ne peut contenir que du texte au format OpenAI-compatible — y
    mettre le base64 brut (via json.dumps sur tout le résultat, comme avant)
    produit un blob texte illisible pour le modèle, image ou pas, multimodal
    ou pas. Les images sont réinjectées séparément en message "user"
    multimodal (voir call_tools), le seul rôle qui supporte un bloc image_url.
    """
    content = result.get("content")
    if not isinstance(content, list):
        return result, []
    images = [b for b in content if isinstance(b, dict) and b.get("type") == "image"]
    if not images:
        return result, []
    rest = [b for b in content if b not in images]
    return {**result, "content": rest or "(voir image ci-dessous)"}, images


async def _call_mcp_tool(client: httpx.AsyncClient, tool_name: str, args: dict) -> tuple[dict, list]:
    """
    Appel HTTP unique à mcp-client:/call, factorisé entre _execute_tool_calls
    (tool_calls décidés par le LLM) et run_slash_command_direct (commande
    tapée directement par l'utilisateur) — même gestion d'erreur/découpage des
    blocs image dans les deux cas.
    """
    try:
        resp = await client.post(
            f"{MCP_CLIENT_URL}/call",
            json={"tool": tool_name, "arguments": args},
        )
        resp.raise_for_status()
        result = resp.json()
    except httpx.HTTPError as exc:
        return {"error": str(exc)}, []
    return _split_image_blocks(result)


async def _execute_tool_calls(state: AgentState, config: dict, *, audit: bool) -> dict:
    """
    Logique partagée entre call_tools (atteint après require_approval, donc
    un humain vient d'examiner ce tour) et auto_call_tools (atteint
    directement depuis has_tool_calls, jamais vu par un humain CE tour-ci).
    `audit` distingue les deux : seul auto_call_tools journalise (Phase 2,
    app/audit_log.py) — un tour passé par require_approval a déjà sa trace
    dans l'historique de conversation ("⚠️ Approbation requise" + la réponse
    de l'utilisateur), inutile de le dupliquer dans le journal d'audit, qui
    sert justement à tracer ce qui n'a PAS été vu par un humain.
    """
    last = state["messages"][-1]
    new_messages = []
    grants = state.get("session_grants") or []
    thread_id = config.get("configurable", {}).get("thread_id", "")

    # Garde-fou fabrication d'URL (Phase 1) : périmètre = URL déjà observées
    # CE tour-ci/tours précédents de la tâche + racines du périmètre (1er
    # message humain). Recalculé/étendu au fil des tool_calls DE CE TOUR
    # (plusieurs browser_* peuvent apparaître dans le même tour_calls).
    observed_urls = set(state.get("observed_urls") or []) | _task_scope_urls(state["messages"])
    current_page_url = state.get("current_page_url")
    current_page_links = state.get("current_page_links") or []
    fabricated_attempts = 0
    # Objectif de la tâche (voir _prioritize_affordances) : le 1er message
    # humain, faute de sous-tâches explicites (Phase 1 complète pas encore
    # faite — ce découpage plus fin viendra avec le nœud planificateur).
    first_human = next((m for m in state["messages"] if getattr(m, "type", None) == "human"), None)
    objective = first_human.content if first_human and isinstance(first_human.content, str) else ""

    # Garde-fou "stratégie différente" (Itération 2, voir
    # _repeated_strategy_feedback) : ne s'applique QUE si un échec de
    # vérification a déjà été constaté sur la sous-tâche active (attempts >
    # 0) — un tout premier essai n'a rien à répéter. Comparaison par
    # égalité stricte nom+args (pas de tolérance ε générique sur des
    # schémas d'arguments arbitraires — simplification assumée).
    plan = state.get("plan") or []
    active_index = _active_subtask_index(plan)
    active_attempts = plan[active_index].get("attempts", 0) if active_index is not None else 0
    # state["messages"][-1] EST `last`, le tour COURANT dont les tool_calls
    # sont en train d'être exécutés — exclu de la recherche (messages[:-1])
    # pour que "previous_tool_calls" désigne vraiment le tour PRÉCÉDENT, pas
    # celui-ci (sans quoi tout tool_call se comparerait à lui-même).
    previous_tool_calls = (
        (_previous_turn_tool_calls(state["messages"][:-1]) or []) if VERIFICATION_ENABLED else []
    )

    async with httpx.AsyncClient(timeout=60) as client:
        for tool_call in last.tool_calls:
            audit_tier = None
            if audit:
                tier = approval_policy.effective_tier(tool_call["name"], tool_call.get("args"), grants)
                if tier == approval_policy.TIER_REVERSIBLE:
                    audit_tier = tier

            blocked = False
            if (
                BROWSER_NAVIGATE_GUARDRAIL
                and tool_call["name"] == "browser_navigate"
                and tool_call.get("args", {}).get("url")
                and tool_call["args"]["url"] not in observed_urls
            ):
                blocked = True
                fabricated_attempts += 1
                attempt_number = state.get("fabricated_navigation_attempts", 0) + fabricated_attempts
                page_links_for_feedback = current_page_links or sorted(observed_urls)
                feedback = _fabrication_feedback(
                    tool_call["args"]["url"], attempt_number, page_links_for_feedback
                )
                result = {"content": [{"type": "text", "text": feedback}]}
                images = []
            elif (
                VERIFICATION_ENABLED
                and active_attempts > 0
                and any(
                    tc.get("name") == tool_call["name"] and tc.get("args") == tool_call.get("args")
                    for tc in previous_tool_calls
                )
            ):
                blocked = True
                result = {"content": [{"type": "text", "text": _repeated_strategy_feedback(tool_call["name"])}]}
                images = []
            else:
                result, images = await _call_mcp_tool(client, tool_call["name"], tool_call["args"])
                if tool_call["name"].startswith("browser_"):
                    result = _truncate_browser_result(result, BROWSER_TOOL_OUTPUT_MAX_CHARS, objective)
                    for block in result.get("content", []) if isinstance(result.get("content"), list) else []:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block["text"]
                            page_url = _extract_page_url(text)
                            if page_url:
                                current_page_url = page_url
                            page_links = _extract_urls(text, current_page_url)
                            if page_links:
                                current_page_links = sorted(page_links)
                            observed_urls |= page_links
                    if tool_call["name"] == "browser_navigate" and not blocked:
                        observed_urls.add(tool_call["args"]["url"])
                        current_page_url = tool_call["args"]["url"]

            if audit_tier is not None:
                # Journalisé APRÈS exécution (voir plus haut) pour porter le
                # résultat tel que vu par le modèle (déjà tronqué/hiérarchisé
                # ci-dessus si browser_*) — voir app/audit_log.py, "Phase
                # 1d-révisée".
                audit_log.log_tool_call(thread_id, tool_call["name"], tool_call["args"], audit_tier, result)

            new_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
            for image in images:
                new_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": _to_image_data_uri(image["data"], image.get("mimeType", "image/png"))
                                },
                            }
                        ],
                    }
                )

    return {
        "messages": new_messages,
        "tool_iterations": state["tool_iterations"] + 1,
        "approved": None,  # réarme la pause pour le prochain tour d'outils
        # Incrémenté systématiquement (tour auto-approuvé ou juste validé par
        # un humain) : require_approval l'a déjà remis à 0 dans ce second cas,
        # donc cette exécution repart correctement à 1 (voir
        # AUTO_APPROVAL_STREAK_LIMIT).
        "auto_approval_streak": state.get("auto_approval_streak", 0) + 1,
        "observed_urls": sorted(observed_urls),
        "current_page_url": current_page_url,
        "current_page_links": current_page_links,
        "fabricated_navigation_attempts": state.get("fabricated_navigation_attempts", 0) + fabricated_attempts,
    }


async def call_tools(state: AgentState, config: dict) -> dict:
    """Atteint après require_approval (humain déjà passé) : jamais audité, voir _execute_tool_calls."""
    return await _execute_tool_calls(state, config, audit=False)


async def auto_call_tools(state: AgentState, config: dict) -> dict:
    """Atteint directement depuis has_tool_calls (aucun humain CE tour) : audité, voir _execute_tool_calls."""
    return await _execute_tool_calls(state, config, audit=True)


async def reject_tools(state: AgentState) -> dict:
    """Miroir de call_tools quand l'humain a refusé : synthétise un refus, n'appelle jamais mcp-client."""
    last = state["messages"][-1]
    new_messages = [
        {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": json.dumps({"error": "Rejeté par l'utilisateur"}, ensure_ascii=False),
        }
        for tool_call in last.tool_calls
    ]
    return {
        "messages": new_messages,
        "tool_iterations": state["tool_iterations"] + 1,
        "approved": None,
    }


_PLAN_STATUS_LABELS_GRAPH = {"a_faire": "à faire", "en_cours": "en cours", "fait": "fait", "echoue": "échoué"}


def _active_subtask_index(plan: list) -> Optional[int]:
    """Index de la sous-tâche "en_cours" du plan, ou None (aucune/plan vide) —
    invariant du plan (Itération 1/2) : au plus une sous-tâche "en_cours" à la fois."""
    return next((i for i, st in enumerate(plan) if st.get("status") == "en_cours"), None)


async def verify_action(state: AgentState) -> dict:
    """
    Vérification post-action (Itération 2, Phase 1 « cœur cognitif »).
    No-op (`{"messages": []}`) si VERIFICATION_ENABLED est désactivé
    (défaut), s'il n'y a pas de sous-tâche "en_cours" (pas de plan, ou plan
    terminé/PLANNER_ENABLED désactivé) ou si le tour qui vient de s'exécuter
    n'a produit aucun résultat d'outil texte.

    Critère vérifié = success_criterion de la sous-tâche ACTIVE du plan
    (Itération 1), pas un critère reformulé à la volée dans le raisonnement
    du tour — voir docs/briefs/phase-1-coeur-cognitif.md, clarification
    obtenue avant cette itération : aucun raisonnement structuré n'existe
    dans ce graphe pour en extraire un fiablement. Depuis l'Itération 4
    (correctif d'ancrage, voir HISTORY.md), le juge reçoit aussi l'objectif
    global de la tâche et, si le tour précédent a utilisé un outil
    browser_*, un browser_snapshot FRAIS de la page — sans quoi il jugeait
    littéralement contre un critère parfois mal ancré (ex. "utilise la
    barre de recherche" sur un site qui n'en a pas), sans jamais voir la
    progression réelle montrée par la page.

    Comme plan_task, dégrade TOUJOURS (verdict "non atteint") plutôt que de
    bloquer la tâche pour un souci de vérification annexe.
    """
    if not VERIFICATION_ENABLED:
        return {"messages": []}
    plan = state.get("plan") or []
    active_index = _active_subtask_index(plan)
    if active_index is None:
        return {"messages": []}
    tool_results = _previous_turn_tool_results(state["messages"])
    if not tool_results:
        return {"messages": []}

    subtask = plan[active_index]
    first_human = next((m for m in state["messages"] if getattr(m, "type", None) == "human"), None)
    objective = first_human.content if first_human and isinstance(first_human.content, str) else ""

    page_snapshot = None
    previous_tool_calls = _previous_turn_tool_calls(state["messages"]) or []
    if any(tc.get("name", "").startswith("browser_") for tc in previous_tool_calls):
        snapshot_text = await _fetch_verification_snapshot(objective)
        page_snapshot = snapshot_text[:4000] if snapshot_text else None

    try:
        response = await planner_llm.ainvoke(
            [
                SystemMessage(content=VERIFIER_SYSTEM_PROMPT),
                HumanMessage(
                    content=json.dumps(
                        {
                            "objectif_global": objective,
                            "sous_tache": subtask["description"],
                            "critere_succes": subtask["success_criterion"],
                            "resultat": "\n".join(tool_results)[:4000],
                            "etat_actuel_de_la_page": page_snapshot,
                        },
                        ensure_ascii=False,
                    )
                ),
            ]
        )
        verdict = _validate_verification_json(response.content)
    except Exception:
        logger.warning("Vérification post-action échouée, tour considéré comme non concluant.", exc_info=True)
        verdict = {"atteint": False, "raison": "vérification indisponible"}

    new_plan = [dict(st) for st in plan]
    if verdict["atteint"]:
        new_plan[active_index]["status"] = "fait"
        new_plan[active_index]["result"] = verdict["raison"]
        if active_index + 1 < len(new_plan):
            new_plan[active_index + 1]["status"] = "en_cours"
        logger.info("Sous-tâche %d atteinte : %s", active_index, verdict["raison"])
        return {"plan": new_plan}

    attempts = new_plan[active_index]["attempts"] + 1
    new_plan[active_index]["attempts"] = attempts
    if attempts < SUBTASK_ATTEMPT_BUDGET:
        logger.info(
            "Sous-tâche %d non atteinte (tentative %d/%d) : %s",
            active_index, attempts, SUBTASK_ATTEMPT_BUDGET, verdict["raison"],
        )
        return {"plan": new_plan}

    new_plan[active_index]["status"] = "echoue"
    new_plan[active_index]["result"] = verdict["raison"]
    logger.warning(
        "Sous-tâche %d échouée après %d tentatives : %s", active_index, attempts, verdict["raison"]
    )
    return {"plan": new_plan}


async def replan_task(state: AgentState) -> dict:
    """
    Replanification (Itération 2) : atteinte quand verify_action a marqué
    une sous-tâche "echoue". Réutilise PLANNER_SYSTEM_PROMPT/
    _validate_plan_json (même schéma que plan_task) avec un prompt de
    contexte (objectif, sous-tâches déjà "fait", raison de l'échec).
    Sous-tâches "fait" préservées telles quelles ; la sous-tâche échouée et
    tout ce qui suivait sont remplacées par la nouvelle décomposition.
    Échec de replanification (LLM/JSON invalide) : repli SANS lever — remet
    juste la sous-tâche échouée à "en_cours"/attempts=0 (nouvelle chance sur
    LE MÊME plan plutôt que de planter). replan_count incrémenté dans tous
    les cas (budget consommé même si la replanification elle-même échoue).
    """
    plan = state.get("plan") or []
    failed_index = next((i for i, st in enumerate(plan) if st.get("status") == "echoue"), None)
    replan_count = state.get("replan_count", 0) + 1
    if failed_index is None:
        return {"replan_count": replan_count}

    first_human = next((m for m in state["messages"] if getattr(m, "type", None) == "human"), None)
    objective = first_human.content if first_human and isinstance(first_human.content, str) else ""
    done = "; ".join(st["description"] for st in plan[:failed_index] if st.get("status") == "fait")
    failure_reason = plan[failed_index].get("result") or "critère non atteint après plusieurs tentatives"
    page_snapshot = await _grounding_snapshot(state, objective)
    snapshot_hint = (
        f"\nÉtat actuel de la page (ce qui est RÉELLEMENT visible maintenant, base-toi dessus) :\n{page_snapshot}\n"
        if page_snapshot
        else ""
    )
    context = (
        f"Objectif original : {objective}\n"
        f"Déjà accompli : {done or 'rien'}\n"
        f"Sous-tâche en échec : {plan[failed_index]['description']} — raison : {failure_reason}\n"
        f"{snapshot_hint}"
        "Replanifie le RESTE de la tâche à partir de maintenant, en tenant compte de cet échec et de ce qui existe réellement."
    )
    try:
        tools_hint = await _available_tools_hint()
        response = await planner_llm.ainvoke(
            [SystemMessage(content=PLANNER_SYSTEM_PROMPT), HumanMessage(content=context + tools_hint)]
        )
        new_subtasks = _validate_plan_json(response.content)
    except Exception:
        logger.warning("Replanification échouée, nouvelle tentative sur la même sous-tâche.", exc_info=True)
        new_plan = [dict(st) for st in plan]
        new_plan[failed_index]["status"] = "en_cours"
        new_plan[failed_index]["attempts"] = 0
        return {"plan": new_plan, "replan_count": replan_count}

    rebuilt = [dict(st) for st in plan[:failed_index]]
    for i, st in enumerate(new_subtasks):
        rebuilt.append({**st, "status": "en_cours" if i == 0 else "a_faire", "attempts": 0, "result": None})
    logger.info(
        "Replanification #%d après échec de la sous-tâche %d : %d nouvelle(s) sous-tâche(s)",
        replan_count, failed_index, len(new_subtasks),
    )
    return {"plan": rebuilt, "replan_count": replan_count}


async def report_failure(state: AgentState) -> dict:
    """
    Terminal (Itération 2) : atteint quand une sous-tâche est "echoue" ET le
    budget de replanification (REPLAN_BUDGET) est épuisé. Rapport HONNÊTE de
    l'état atteint — jamais un faux succès, jamais une boucle infinie.
    """
    plan = state.get("plan") or []
    lines = ["Je n'ai pas pu terminer la tâche avec le budget de tentatives/replanifications disponible."]
    lines.append("État atteint :")
    for st in plan:
        label = _PLAN_STATUS_LABELS_GRAPH.get(st.get("status"), st.get("status", "?"))
        detail = f" — {st['result']}" if st.get("result") else ""
        lines.append(f"- [{label}] {st.get('description', '')}{detail}")
    return {"messages": [{"role": "assistant", "content": "\n".join(lines)}]}


def route_after_verification(state: AgentState) -> str:
    """
    Routage après verify_action (Itération 2). VERIFICATION_ENABLED
    désactivé ou aucune sous-tâche "echoue" -> "continue" (flux normal,
    identique à avant cette itération). Sous-tâche "echoue" -> "replan" tant
    que le budget REPLAN_BUDGET n'est pas épuisé, sinon "give_up" (rapport
    d'échec honnête plutôt qu'une boucle infinie de replanifications).
    """
    plan = state.get("plan") or []
    if any(st.get("status") == "echoue" for st in plan):
        if state.get("replan_count", 0) < REPLAN_BUDGET:
            return "replan"
        return "give_up"
    return "continue"


def _coerce_slash_arg_value(raw: str):
    """int > float > bool ("true"/"false") > string, dans cet ordre."""
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    return raw


def _parse_slash_command(content: str) -> Optional[tuple]:
    """
    "/toolname a=1 b=texte" -> ("toolname", {"a": 1, "b": "texte"}).
    None si le contenu ne commence pas par "/" ou est vide après le "/".
    shlex.split gère les valeurs entre guillemets contenant des espaces. Un
    token sans "=" (argument malformé) est simplement ignoré (log warning)
    plutôt que de faire échouer tout le parsing d'une commande par ailleurs
    valide.
    """
    if not content or not content.startswith("/"):
        return None
    try:
        tokens = shlex.split(content[1:])
    except ValueError:
        return None
    if not tokens:
        return None
    tool_name = tokens[0]
    args = {}
    for tok in tokens[1:]:
        if "=" not in tok:
            logger.warning("Argument de commande slash ignoré (pas de '=') : %r", tok)
            continue
        key, _, raw_value = tok.partition("=")
        args[key] = _coerce_slash_arg_value(raw_value)
    return tool_name, args


def _format_tool_result_as_text(result: dict) -> str:
    """Extrait le texte des blocs {"type": "text", ...} du résultat d'outil ;
    à défaut (résultat vide, erreur, forme inattendue), JSON indenté brut."""
    blocks = result.get("content", []) if isinstance(result, dict) else []
    if isinstance(blocks, str):
        # _split_image_blocks retombe sur ce placeholder textuel quand TOUS
        # les blocs du résultat étaient des images (ex. screen_shot seul) —
        # ce n'est déjà pas une liste de blocs, le renvoyer tel quel plutôt
        # que d'itérer sur ses caractères (aucun n'est un dict "text", donc
        # ça retombait silencieusement sur un dump JSON de tout le dict).
        return blocks
    texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    if texts:
        return "\n".join(texts)
    return json.dumps(result, ensure_ascii=False, indent=2)


async def prepare_slash_command(state: AgentState, config: dict) -> dict:
    """
    Parse la commande slash et synthétise le tool_calls correspondant, sans
    encore l'exécuter — le routage par tier (_route_slash_command_tier)
    décide ensuite si ça part en direct (run_slash_command_direct) ou par la
    vraie pause d'approbation (require_approval), selon le tier de l'outil.
    """
    tool_name, args = _parse_slash_command(state["messages"][-1].content)
    call_id = f"slash_{uuid.uuid4().hex[:12]}"
    return {
        "messages": [
            {"role": "assistant", "content": "", "tool_calls": [{"name": tool_name, "args": args, "id": call_id}]}
        ]
    }


def _route_slash_command_tier(state: AgentState) -> str:
    """
    GARDE-FOU : une commande slash sur un outil TIER_SENSITIVE (ex. key_type
    avec texte long, clipboard_get) ne s'exécute PAS directement — elle part
    par require_approval, exactement comme un tool_calls décidé par le LLM.
    Le fait de taper explicitement la commande ne vaut approbation que pour
    TIER_READ/TIER_REVERSIBLE : le tier sensible existe précisément pour
    imposer une confirmation séparée avant une action potentiellement
    dangereuse (texte libre tapé dans un terminal, exfiltration du
    presse-papier...) — un bypass total aurait annulé cette garantie pour
    n'importe quel outil, y compris ceux jamais voulus auto-approuvés.
    """
    last = state["messages"][-1]
    tool_call = last.tool_calls[0]
    grants = state.get("session_grants") or []
    tier = approval_policy.effective_tier(tool_call["name"], tool_call.get("args"), grants)
    return "sensitive" if tier == approval_policy.TIER_SENSITIVE else "direct"


async def run_slash_command_direct(state: AgentState, config: dict) -> dict:
    """
    Exécute directement le tool_calls synthétisé par prepare_slash_command
    (tier lecture/réversible uniquement, voir _route_slash_command_tier) —
    ni LLM ni pause d'approbation. Termine sur un AIMessage de forme
    standard (pas juste le ToolMessage brut) pour rester compatible sans
    aucune modification avec main.py, qui suppose que le dernier message
    d'un tour terminé est un AIMessage avec du contenu visible (voir
    _stream_response/_current_answer, qui basculeraient sinon sur la notice
    "réponse non exploitable").
    """
    last = state["messages"][-1]
    tool_call = last.tool_calls[0]
    tool_name, args, call_id = tool_call["name"], tool_call["args"], tool_call["id"]

    # Traçabilité uniquement (parité avec auto_call_tools) : n'influence
    # jamais l'exécution — le tier sensible a déjà été écarté par
    # _route_slash_command_tier avant d'arriver ici.
    grants = state.get("session_grants") or []
    tier = approval_policy.effective_tier(tool_name, args, grants)
    thread_id = config.get("configurable", {}).get("thread_id", "")

    async with httpx.AsyncClient(timeout=60) as client:
        result, images = await _call_mcp_tool(client, tool_name, args)

    if tier == approval_policy.TIER_REVERSIBLE:
        audit_log.log_tool_call(thread_id, tool_name, args, tier, result)

    new_messages = [
        {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False)},
    ]
    for image in images:
        new_messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": _to_image_data_uri(image["data"], image.get("mimeType", "image/png"))
                        },
                    }
                ],
            }
        )
    # Le message "user" ci-dessus (bloc image_url standard) est ce que voit
    # un futur tour LLM sur ce thread — format efficace pour un modèle
    # multimodal (coût fixe par image côté API), PAS de base64 embarqué en
    # texte brut dans le message assistant final : un essai précédent
    # embarquait l'image en markdown directement ici, ce qui la faisait
    # certes apparaître dans CETTE réponse, mais la persistait aussi dans
    # l'historique sous forme de texte — tokenisée comme du texte ordinaire
    # (des dizaines de milliers de tokens pour une seule capture) au lieu du
    # coût fixe d'un vrai bloc image_url, faisant exploser le contexte
    # (32768 tokens dépassés) dès le tour LLM suivant sur ce thread, même
    # avec une seule image (MAX_IMAGES_IN_CONTEXT=1 ne trimme jamais LA
    # dernière image, donc aucune protection possible sous cette forme).
    # L'affichage de l'image POUR CE TOUR est reconstruit côté main.py
    # (_render_visible_answer) à partir de ce message "user" séparé, jamais
    # en la persistant une seconde fois ici.
    new_messages.append({"role": "assistant", "content": _format_tool_result_as_text(result)})

    return {
        "messages": new_messages,
        "tool_iterations": state["tool_iterations"] + 1,
        "slash_command_image_shown": bool(images),
    }


async def _route_entry(state: AgentState) -> str:
    """
    Point d'entrée conditionnel du graphe : bascule sur prepare_slash_command
    si le dernier message est une commande slash dont le nom d'outil est
    CONNU (_tools_schema_cache, format OpenAI function-calling imbriqué
    {"function": {"name": ...}}, voir mcp-client:/tools/schema) — un message
    qui commence juste par "/" sans être une commande valide (ex. un chemin
    de fichier) suit le flux normal plutôt que de déclencher une erreur 404
    confuse pour un nom qui n'était jamais censé être un outil.
    """
    parsed = _parse_slash_command(state["messages"][-1].content)
    if parsed is None:
        return "normal"
    tool_name, _ = parsed
    schema = await _get_tools_schema()
    known_names = {t.get("function", {}).get("name") for t in schema}
    return "slash_command" if tool_name in known_names else "normal"


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)
    graph.add_node("retrieve_context", retrieve_context)
    graph.add_node("select_skill", select_skill)
    graph.add_node("plan_task", plan_task)
    graph.add_node("validate_plan", validate_plan)
    graph.add_node("revise_plan", revise_plan)
    graph.add_node("require_plan_approval", require_plan_approval)
    graph.add_node("reject_plan", reject_plan)
    graph.add_node("call_llm", call_llm)
    graph.add_node("require_approval", require_approval)
    graph.add_node("call_tools", call_tools)
    graph.add_node("auto_call_tools", auto_call_tools)
    graph.add_node("verify_action", verify_action)
    graph.add_node("replan_task", replan_task)
    graph.add_node("report_failure", report_failure)
    graph.add_node("reject_tools", reject_tools)
    graph.add_node("retry_empty_answer", retry_empty_answer)
    graph.add_node("prepare_slash_command", prepare_slash_command)
    graph.add_node("run_slash_command_direct", run_slash_command_direct)

    graph.set_conditional_entry_point(
        _route_entry, {"slash_command": "prepare_slash_command", "normal": "retrieve_context"}
    )
    graph.add_conditional_edges(
        "prepare_slash_command",
        _route_slash_command_tier,
        {"sensitive": "require_approval", "direct": "run_slash_command_direct"},
    )
    graph.add_edge("run_slash_command_direct", END)
    graph.add_edge("retrieve_context", "select_skill")
    graph.add_edge("select_skill", "plan_task")
    graph.add_edge("plan_task", "validate_plan")
    graph.add_conditional_edges(
        "validate_plan",
        route_after_validation,
        {"call_llm": "call_llm", "revise_plan": "revise_plan", "require_plan_approval": "require_plan_approval"},
    )
    graph.add_edge("revise_plan", "validate_plan")
    graph.add_conditional_edges(
        "require_plan_approval",
        route_after_plan_approval,
        {"call_llm": "call_llm", "reject_plan": "reject_plan"},
    )
    graph.add_edge("reject_plan", END)
    graph.add_conditional_edges(
        "call_llm",
        has_tool_calls,
        {
            "call_tools": "require_approval",
            "auto_call_tools": "auto_call_tools",
            "retry_empty_answer": "retry_empty_answer",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "require_approval", route_after_approval, {"call_tools": "call_tools", "reject_tools": "reject_tools"}
    )
    graph.add_edge("call_tools", "verify_action")
    graph.add_edge("auto_call_tools", "verify_action")
    graph.add_conditional_edges(
        "verify_action",
        route_after_verification,
        {"continue": "call_llm", "replan": "replan_task", "give_up": "report_failure"},
    )
    graph.add_edge("replan_task", "validate_plan")
    graph.add_edge("report_failure", END)
    graph.add_edge("reject_tools", "call_llm")
    graph.add_edge("retry_empty_answer", "call_llm")

    return graph.compile(checkpointer=checkpointer or MemorySaver())


agent_graph = build_graph()
