# Instruction particulières pour ce projet

1. lis le README.md en début de session
2. les bugs résolus doivent être inscrits dans BUGS.md
3. l'historique des avancées doit être inscrit dans HISTORY.md
4. toujours informer l'utilisateur des commandes qu'il doit tapper si besoin de redémarrer/rebuild un service docker
5. une phase = une PR.
6. STOP 🧑 aux checkpoints.
7. Pas de refactor opportuniste hors périmètre — le proposer au checkpoint.
8. Toute affirmation sur le comportement d'une lib se vérifie contre le code installé.
9. README mis à jour au fil de l'eau, style existant.
10. Suggérer des simplification évidentes quand c'est opportun


# Contexte

La stack sert désormais Qwen3.6-27B EXL3 via
TabbyAPI/ExLlamaV3 (dual-GPU, vision + MTP), le trio langgraph/langchain-openai/
openai est migré en 1.x/2.x, et un serveur MCP Playwright est branché aux côtés
de GhostDesk. Objectif du chantier : faire passer l'agent de « exécute des
actions approuvées » à « accomplit des tâches web multi-étapes en autonomie »,
sans affaiblir le modèle de sécurité existant (tiers d'approbation, PromptGuard,
firewall egress).


# Plan de développement

Voir `PLAN.md` — plan détaillé par phases (0 à 4), amendements intégrés.