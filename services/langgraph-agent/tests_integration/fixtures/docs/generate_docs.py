"""
Générateur du fixture "docs" (Benchmark 0, T4 — voir BENCHMARK0.md). ~30 pages
de documentation, sommaire de navigation, recherche JS côté client (index
JSON statique + filtrage), et une piste à 2 sauts pour `max_retry_delay` :
la recherche mène à une page "index des paramètres réseau" qui renvoie elle-
même vers la page "config-reseau-avancee" où la valeur est documentée.

Déterministe (contenu fixe, pas de seed nécessaire ici — tout est explicite).

Usage : python3 generate_docs.py <dossier_de_sortie>
"""
import hashlib
import json
import sys
from pathlib import Path

N_FILLER_PAGES = 27  # + la page d'accueil + la page intermédiaire + la page cible = 30

TARGET_PARAM = "max_retry_delay"
TARGET_DEFAULT = "30000"
TARGET_PAGE = "config-reseau-avancee"
INTERMEDIATE_PAGE = "index-parametres-reseau"

PAGE_TEMPLATE = """<!doctype html>
<html lang="fr">
<head><meta charset="utf-8"><title>{title}</title></head>
<body>
<nav><a href="/docs/index.html">Sommaire</a> | <a href="/docs/search.html">Recherche</a></nav>
<h1>{title}</h1>
{body}
</body>
</html>
"""


def _filler_page(n: int) -> str:
    return PAGE_TEMPLATE.format(
        title=f"Section {n}",
        body=f"<p>Documentation de la section {n}. Contenu générique sans rapport avec les paramètres réseau.</p>",
    )


def generate(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = {}

    for n in range(1, N_FILLER_PAGES + 1):
        pages[f"section-{n}"] = _filler_page(n)

    # Page intermédiaire : ne donne PAS la valeur, renvoie vers la page cible.
    pages[INTERMEDIATE_PAGE] = PAGE_TEMPLATE.format(
        title="Index des paramètres réseau",
        body=(
            "<p>Cette page recense les catégories de paramètres réseau. "
            "Pour la configuration avancée des tentatives de reconnexion, "
            f'voir <a href="/docs/{TARGET_PAGE}.html">Configuration réseau avancée</a>.</p>'
        ),
    )

    # Page cible : tableau de paramètres avec la valeur exacte.
    pages[TARGET_PAGE] = PAGE_TEMPLATE.format(
        title="Configuration réseau avancée",
        body=(
            "<table>"
            "<tr><th>Paramètre</th><th>Valeur par défaut</th><th>Description</th></tr>"
            f"<tr><td>{TARGET_PARAM}</td><td>{TARGET_DEFAULT}</td>"
            "<td>Délai maximal (ms) avant nouvelle tentative après échec réseau.</td></tr>"
            "<tr><td>connect_timeout</td><td>5000</td><td>Délai de connexion initial (ms).</td></tr>"
            "<tr><td>max_retries</td><td>3</td><td>Nombre maximal de tentatives.</td></tr>"
            "</table>"
        ),
    )

    for slug, html in pages.items():
        (out_dir / f"{slug}.html").write_text(html, encoding="utf-8")

    # Sommaire
    toc_items = "\n".join(
        f'<li><a href="/docs/{slug}.html">{slug}</a></li>' for slug in sorted(pages)
    )
    index_html = PAGE_TEMPLATE.format(
        title="Documentation — Sommaire",
        body=f"<ul>{toc_items}</ul>",
    )
    (out_dir / "index.html").write_text(index_html, encoding="utf-8")

    # Index de recherche JSON (titre + slug), consommé par search.html en JS pur.
    search_index = [
        {"slug": slug, "title": html.split("<h1>")[1].split("</h1>")[0]}
        for slug, html in pages.items()
    ]
    # Entrée dédiée pour que la recherche "max_retry_delay" trouve la page
    # intermédiaire en premier (comme documenté par construction), pas la
    # page cible directement — la piste à 2 sauts est le point testé.
    search_index.append(
        {"slug": INTERMEDIATE_PAGE, "title": "Index des paramètres réseau (max_retry_delay)"}
    )
    (out_dir / "search-index.json").write_text(
        json.dumps(search_index, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    search_html = """<!doctype html>
<html lang="fr">
<head><meta charset="utf-8"><title>Recherche</title></head>
<body>
<nav><a href="/docs/index.html">Sommaire</a></nav>
<h1>Recherche</h1>
<input type="text" id="q" placeholder="Rechercher...">
<button id="go">Rechercher</button>
<ul id="results"></ul>
<script>
async function search() {
  const q = document.getElementById('q').value.toLowerCase();
  const resp = await fetch('/docs/search-index.json');
  const index = await resp.json();
  const results = index.filter(e => e.title.toLowerCase().includes(q));
  const ul = document.getElementById('results');
  ul.innerHTML = '';
  for (const r of results) {
    const li = document.createElement('li');
    li.innerHTML = '<a href="/docs/' + r.slug + '.html">' + r.title + '</a>';
    ul.appendChild(li);
  }
}
document.getElementById('go').addEventListener('click', search);
document.getElementById('q').addEventListener('keydown', e => { if (e.key === 'Enter') search(); });
</script>
</body>
</html>
"""
    (out_dir / "search.html").write_text(search_html, encoding="utf-8")

    sha = hashlib.sha256()
    for f in sorted(out_dir.glob("*")):
        if f.name == "HASHES.txt":
            continue
        sha.update(f.name.encode())
        sha.update(f.read_bytes())
    (out_dir / "HASHES.txt").write_text(f"sha256:{sha.hexdigest()}\n", encoding="utf-8")


if __name__ == "__main__":
    generate(Path(sys.argv[1] if len(sys.argv) > 1 else "site"))
