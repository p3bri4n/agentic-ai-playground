"""
Matching insensible à la casse pour find_text : sous-chaîne d'abord (rapide,
suffisant pour la majorité des requêtes), puis distance de Levenshtein
"légère" en secours si fuzzy=True, pour tolérer les erreurs de lecture
ponctuelles de l'OCR (ex. "Parametres" détecté au lieu de "Paramètres").

La distance s'applique MOT PAR MOT (pas sur la ligne détectée entière) :
comparer une requête courte à une ligne longue via Levenshtein sur la ligne
entière pénaliserait injustement toute correspondance partielle, alors que
comparer aux mots individuels de la ligne capture l'intention réelle
(l'utilisateur cherche un mot ou une courte expression, pas un paragraphe).
"""


def _normalize(text: str) -> str:
    return text.casefold()


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))

    previous_row = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current_row = [i] + [0] * len(b)
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            current_row[j] = min(
                previous_row[j] + 1,        # suppression
                current_row[j - 1] + 1,     # insertion
                previous_row[j - 1] + cost,  # substitution
            )
        previous_row = current_row
    return previous_row[-1]


def matches(query: str, detected_text: str, fuzzy: bool = True) -> bool:
    normalized_query = _normalize(query)
    normalized_text = _normalize(detected_text)

    if normalized_query in normalized_text:
        return True
    if not fuzzy or not normalized_query:
        return False

    # Tolérance proportionnelle à la longueur de la requête plutôt qu'un
    # seuil fixe : un mot d'1-2 lettres ne doit tolérer aucune erreur, un
    # mot long peut en tolérer plusieurs.
    max_distance = max(1, len(normalized_query) // 4)
    return any(
        _levenshtein(normalized_query, word) <= max_distance
        for word in normalized_text.split()
    )
