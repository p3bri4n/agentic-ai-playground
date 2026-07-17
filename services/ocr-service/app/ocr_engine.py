"""
Moteur OCR : PaddleOCR en CPU (les deux GPU sont déjà saturés par llama-server,
voir README) pour find_text/read_screen.

Langues fr + en : PaddleOCR regroupe le français et l'anglais (alphabet latin)
sous un seul modèle de reconnaissance ("lang=fr" couvre déjà l'anglais en
pratique, les deux partagent le même jeu de caractères latins) — inutile de
faire tourner deux passes OCR séparées pour ce projet. OCR_LANGS reste
configurable si un déploiement a besoin d'un autre alphabet.

En environnement de test, OCR_ENGINE=fake bascule sur un moteur déterministe
sans dépendance à PaddleOCR (même principe que EMBEDDING_MODEL=fake du
context-manager) : les détections retournées sont injectées par le test via
set_fake_detections(), jamais calculées à partir de l'image reçue.
"""

import os

OCR_ENGINE_NAME = os.environ.get("OCR_ENGINE", "paddleocr")
OCR_LANGS = os.environ.get("OCR_LANGS", "fr")

_fake_detections: list[dict] = []


def set_fake_detections(detections: list[dict]) -> None:
    """Réservé aux tests (OCR_ENGINE=fake) : contrôle ce que renvoie FakeOCREngine.run()."""
    global _fake_detections
    _fake_detections = detections


class FakeOCREngine:
    def run(self, image_bytes: bytes) -> list[dict]:
        return [dict(detection) for detection in _fake_detections]


class PaddleOCREngine:
    def __init__(self, lang: str):
        # import paresseux : seuls les déploiements qui ne fixent pas
        # OCR_ENGINE=fake ont besoin de paddleocr/paddlepaddle, dépendances
        # lourdes absentes de l'environnement de test.
        from paddleocr import PaddleOCR

        self._ocr = PaddleOCR(use_angle_cls=False, lang=lang, show_log=False)

    def run(self, image_bytes: bytes) -> list[dict]:
        import io

        import numpy as np
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as image:
            array = np.array(image.convert("RGB"))

        result = self._ocr.ocr(array, cls=False)
        lines = result[0] if result else []

        detections = []
        for box, (text, confidence) in lines or []:
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            x, y = min(xs), min(ys)
            detections.append(
                {
                    "text": text,
                    "x": x,
                    "y": y,
                    "width": max(xs) - x,
                    "height": max(ys) - y,
                    "confidence": float(confidence),
                }
            )
        return detections


def get_engine():
    if OCR_ENGINE_NAME == "fake":
        return FakeOCREngine()
    return PaddleOCREngine(lang=OCR_LANGS)
