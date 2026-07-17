"""
Conversion des coordonnées OCR (pixels réels de la capture) vers le repère
normalisé 0-1000 attendu par mouse_click côté GhostDesk (voir
GHOSTDESK_MODEL_SPACE dans mcp-client, même repère utilisé par les modèles
Qwen) — source classique de clics décalés si oubliée : GhostDesk interprète
par défaut les coordonnées reçues comme des pixels écran natifs, alors que le
LLM raisonne (et cliquera donc) dans l'espace 0-1000.

OCR_COORD_SPACE=pixels désactive cette conversion (coordonnées OCR brutes),
utile si le service appelant mouse_click travaille lui-même en pixels.
"""

COORD_SPACE_NORMALIZED = "1000"
COORD_SPACE_PIXELS = "pixels"


def _to_normalized(value_px: float, dimension_px: int) -> int:
    return round(value_px * 1000 / dimension_px)


def convert_detection(detection: dict, image_width: int, image_height: int, coord_space: str) -> dict:
    if coord_space == COORD_SPACE_PIXELS:
        return detection

    return {
        **detection,
        "x": _to_normalized(detection["x"], image_width),
        "y": _to_normalized(detection["y"], image_height),
        "width": _to_normalized(detection["width"], image_width),
        "height": _to_normalized(detection["height"], image_height),
    }
