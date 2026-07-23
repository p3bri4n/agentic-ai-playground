"""
Données figées du fixture "hr-app" (Benchmark 0, T2/T3/T5/T6 — voir
BENCHMARK0.md). Tout est déterministe et codé en dur (pas de génération
aléatoire ici, contrairement à catalog/docs) : les valeurs de vérité terrain
(3e salaire Ingénierie, masse salariale Ventes, nombre de demandes "en
attente") sont calculées une fois ici et exposées à la fois à l'app Flask et
au harnais de test, pour ne jamais dupliquer une valeur à la main des deux
côtés.
"""

LOGIN_USERNAME = "rh.manager"
LOGIN_PASSWORD = "Conges2026!"

# Volontairement PAS trié par salaire ni groupé par département dans l'ordre
# de la liste : force un vrai tri/filtre JS côté page plutôt qu'une lecture
# de l'ordre par défaut (voir T3, BENCHMARK0.md).
EMPLOYEES = [
    {"id": 1, "name": "Julien Faure", "department": "Ingénierie", "salary": 52000},
    {"id": 2, "name": "Camille Roux", "department": "Ventes", "salary": 38000},
    {"id": 3, "name": "Sophie Bernard", "department": "Ingénierie", "salary": 61000},
    {"id": 4, "name": "Karim Haddad", "department": "RH", "salary": 41000},
    {"id": 5, "name": "Élise Petit", "department": "Ventes", "salary": 44500},
    {"id": 6, "name": "Thomas Girard", "department": "Ingénierie", "salary": 47000},
    {"id": 7, "name": "Nadia Cohen", "department": "Marketing", "salary": 39500},
    {"id": 8, "name": "Antoine Leroy", "department": "Ingénierie", "salary": 58000},
    {"id": 9, "name": "Marion Dubois", "department": "Ventes", "salary": 36000},
    {"id": 10, "name": "Yann Morel", "department": "RH", "salary": 40000},
    {"id": 11, "name": "Léa Fontaine", "department": "Ingénierie", "salary": 55000},
    {"id": 12, "name": "Hugo Lambert", "department": "Marketing", "salary": 42000},
    {"id": 13, "name": "Inès Marchand", "department": "Ventes", "salary": 41000},
    {"id": 14, "name": "Paul Renard", "department": "Ingénierie", "salary": 49500},
    {"id": 15, "name": "Chloé Simon", "department": "RH", "salary": 39000},
    {"id": 16, "name": "Victor Perrin", "department": "Ventes", "salary": 39500},
    {"id": 17, "name": "Amandine Blanc", "department": "Marketing", "salary": 37000},
]

# Vérité terrain T3 : 3e salaire le plus élevé du département Ingénierie.
_ingenierie = sorted(
    (e for e in EMPLOYEES if e["department"] == "Ingénierie"),
    key=lambda e: e["salary"],
    reverse=True,
)
T3_ANSWER_NAME = _ingenierie[2]["name"]  # 3e position (index 2)

# Vérité terrain T5 : masse salariale totale du département Ventes.
T5_ANSWER_TOTAL = sum(e["salary"] for e in EMPLOYEES if e["department"] == "Ventes")

# Demandes de congé pré-existantes (visibles seulement après login, T6).
# Statuts fixes : 3 "en attente", le reste résolu, pour une vérité terrain
# non ambiguë.
LEAVE_REQUESTS = [
    {"employee": "Julien Faure", "status": "en attente"},
    {"employee": "Camille Roux", "status": "approuvée"},
    {"employee": "Sophie Bernard", "status": "en attente"},
    {"employee": "Karim Haddad", "status": "refusée"},
    {"employee": "Élise Petit", "status": "approuvée"},
    {"employee": "Thomas Girard", "status": "en attente"},
    {"employee": "Nadia Cohen", "status": "approuvée"},
]

T6_ANSWER_PENDING_COUNT = sum(1 for r in LEAVE_REQUESTS if r["status"] == "en attente")
