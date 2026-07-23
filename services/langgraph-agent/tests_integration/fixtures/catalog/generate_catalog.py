"""
Générateur du fixture "catalog" (Benchmark 0, T1 — voir BENCHMARK0.md à la
racine de tests_integration/). Déterministe (seed fixe) : rejouer ce script
produit TOUJOURS le même site, condition pour que le fixture reste "figé"
(hash consigné, voir HASHES.txt généré à côté du site).

30 produits, 3 pages de 10 (liste : nom + lien seulement, ni prix ni
référence — l'un et l'autre ne sont visibles que sur la fiche produit
individuelle, pour forcer une navigation ciblée plutôt qu'une lecture de la
liste). Un seul produit porte la référence KX-4471, page 2 de la liste.

Échelle réduite délibérément (voir HISTORY.md, recalibrage T1) : une version
initiale à 120 produits/12 pages rendait la recherche exhaustive du pire cas
(ouvrir chaque fiche jusqu'à trouver la référence) incompatible avec
MAX_TOOL_ITERATIONS — mesurait une mauvaise calibration du fixture, pas la
capacité de navigation de l'agent.

Usage : python3 generate_catalog.py <dossier_de_sortie>
"""
import hashlib
import random
import sys
from pathlib import Path

SEED = 42
N_PRODUCTS = 30
PER_PAGE = 10
N_PAGES = N_PRODUCTS // PER_PAGE

ADJECTIFS = [
    "Compact", "Robuste", "Élégant", "Portable", "Premium", "Classique",
    "Moderne", "Léger", "Puissant", "Silencieux", "Durable", "Précis",
]
NOMS = [
    "Lampe", "Sacoche", "Clavier", "Chaise", "Étagère", "Casque",
    "Thermos", "Carnet", "Ventilateur", "Support", "Rallonge", "Tapis",
]

# La cible T1 : référence unique, injectée explicitement page 2 (produits 11-20)
TARGET_REF = "KX-4471"
TARGET_INDEX = 14  # 1-indexé, page 2 (produits 11-20)
TARGET_PRICE = "84.90"


def _reference(i: int) -> str:
    if i == TARGET_INDEX:
        return TARGET_REF
    # références plausibles mais jamais égales à TARGET_REF par construction
    return f"PX-{1000 + i}"


def _product_name(rng: random.Random, i: int) -> str:
    return f"{rng.choice(ADJECTIFS)} {rng.choice(NOMS)} #{i}"


def _price(rng: random.Random, i: int) -> str:
    if i == TARGET_INDEX:
        return TARGET_PRICE
    return f"{rng.uniform(9.90, 199.90):.2f}"


def _stock(rng: random.Random, i: int) -> int:
    return rng.randint(0, 50)


PAGE_TEMPLATE = """<!doctype html>
<html lang="fr">
<head><meta charset="utf-8"><title>Catalogue — page {page}</title></head>
<body>
<h1>Catalogue produits</h1>
<ul>
{items}
</ul>
<nav>
{nav}
</nav>
</body>
</html>
"""

PRODUCT_TEMPLATE = """<!doctype html>
<html lang="fr">
<head><meta charset="utf-8"><title>{name}</title></head>
<body>
<h1>{name}</h1>
<dl>
<dt>Référence</dt><dd id="reference">{reference}</dd>
<dt>Prix</dt><dd id="price">{price} €</dd>
<dt>Stock</dt><dd id="stock">{stock}</dd>
</dl>
<a href="/catalog/page-{page}.html">Retour à la liste</a>
</body>
</html>
"""


def generate(out_dir: Path) -> None:
    rng = random.Random(SEED)
    out_dir.mkdir(parents=True, exist_ok=True)
    products = []
    for i in range(1, N_PRODUCTS + 1):
        products.append(
            {
                "i": i,
                "name": _product_name(rng, i),
                "reference": _reference(i),
                "price": _price(rng, i),
                "stock": _stock(rng, i),
                "page": (i - 1) // PER_PAGE + 1,
            }
        )

    for p in products:
        html = PRODUCT_TEMPLATE.format(
            name=p["name"], reference=p["reference"], price=p["price"],
            stock=p["stock"], page=p["page"],
        )
        (out_dir / f"product-{p['i']}.html").write_text(html, encoding="utf-8")

    for page in range(1, N_PAGES + 1):
        page_products = [p for p in products if p["page"] == page]
        items = "\n".join(
            f'<li><a href="/catalog/product-{p["i"]}.html">{p["name"]}</a></li>'
            for p in page_products
        )
        nav_links = []
        if page > 1:
            nav_links.append(f'<a href="/catalog/page-{page - 1}.html">Précédent</a>')
        if page < N_PAGES:
            nav_links.append(f'<a href="/catalog/page-{page + 1}.html">Suivant</a>')
        nav = " | ".join(nav_links)
        html = PAGE_TEMPLATE.format(page=page, items=items, nav=nav)
        (out_dir / f"page-{page}.html").write_text(html, encoding="utf-8")

    index_html = (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        "<title>Catalogue</title></head><body>"
        '<h1>Catalogue produits</h1>'
        '<p><a href="/catalog/page-1.html">Voir le catalogue</a></p>'
        "</body></html>"
    )
    (out_dir / "index.html").write_text(index_html, encoding="utf-8")

    # Hash de tout le site généré, pour détecter toute dérive du générateur
    # (fixture "figée" par construction, voir BENCHMARK0.md).
    sha = hashlib.sha256()
    for f in sorted(out_dir.glob("*.html")):
        sha.update(f.name.encode())
        sha.update(f.read_bytes())
    (out_dir / "HASHES.txt").write_text(f"sha256:{sha.hexdigest()}\n", encoding="utf-8")


if __name__ == "__main__":
    generate(Path(sys.argv[1] if len(sys.argv) > 1 else "site"))
