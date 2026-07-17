from app.matching import matches


def test_exact_substring_match_is_case_insensitive():
    assert matches("fichier", "Menu Fichier") is True
    assert matches("FICHIER", "menu fichier") is True


def test_fuzzy_tolerates_a_single_ocr_misread_character():
    # "Parametres" (sans accent, erreur de lecture OCR plausible) doit tout
    # de même matcher la requête "Paramètres" quand fuzzy=True.
    assert matches("Paramètres", "Parametres avancés", fuzzy=True) is True


def test_fuzzy_disabled_requires_exact_substring():
    assert matches("Paramètres", "Parametres avancés", fuzzy=False) is False


def test_no_match_returns_false_never_raises():
    assert matches("motintrouvable", "Fichier Édition Affichage", fuzzy=True) is False


def test_empty_query_never_fuzzy_matches_everything():
    assert matches("", "Fichier", fuzzy=True) is True  # "" est une sous-chaîne de tout
    assert matches("xyz", "Fichier", fuzzy=True) is False
