from app.coords import convert_detection

# Résolution documentée dans le README (bureau GhostDesk par défaut).
IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 1024


def _detection(x, y, width, height):
    return {"text": "x", "x": x, "y": y, "width": width, "height": height, "confidence": 0.9}


def test_pixels_converted_to_normalized_1000_space():
    detection = _detection(x=640, y=512, width=128, height=32)

    result = convert_detection(detection, IMAGE_WIDTH, IMAGE_HEIGHT, coord_space="1000")

    assert result["x"] == 500     # 640 * 1000 / 1280
    assert result["y"] == 500     # 512 * 1000 / 1024
    assert result["width"] == 100  # 128 * 1000 / 1280
    assert result["height"] == 31  # round(32 * 1000 / 1024) == round(31.25)


def test_top_left_corner_maps_to_origin():
    detection = _detection(x=0, y=0, width=0, height=0)

    result = convert_detection(detection, IMAGE_WIDTH, IMAGE_HEIGHT, coord_space="1000")

    assert result["x"] == 0
    assert result["y"] == 0


def test_pixels_space_disables_conversion():
    detection = _detection(x=640, y=512, width=128, height=32)

    result = convert_detection(detection, IMAGE_WIDTH, IMAGE_HEIGHT, coord_space="pixels")

    assert result == detection


def test_text_and_confidence_are_preserved():
    detection = {"text": "Fichier", "x": 10, "y": 20, "width": 50, "height": 15, "confidence": 0.87}

    result = convert_detection(detection, IMAGE_WIDTH, IMAGE_HEIGHT, coord_space="1000")

    assert result["text"] == "Fichier"
    assert result["confidence"] == 0.87
