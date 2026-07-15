from __future__ import annotations


class ImageQualityAssessor:
    """Self-hosted image-quality assessment for Agent 1 (final target plan.md Section
    6): blur (Laplacian variance), resolution, and brightness via OpenCV, replacing
    the previous hardcoded `quality=0.9` fixture constant that ignored the actual
    uploaded photo entirely. No API key required.
    """

    _MIN_DIMENSION = 600
    _BLUR_VARIANCE_THRESHOLD = 100.0
    _BRIGHTNESS_RANGE = (40.0, 220.0)

    def assess(self, image_bytes: bytes) -> dict[str, float | int]:
        import cv2
        import numpy as np

        array = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if image is None:
            return {"quality": 0.0, "blur_variance": 0.0, "width": 0, "height": 0, "brightness": 0.0}

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blur_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        height, width = gray.shape[:2]
        brightness = float(gray.mean())

        blur_score = min(1.0, blur_variance / self._BLUR_VARIANCE_THRESHOLD)
        resolution_score = min(1.0, min(width, height) / self._MIN_DIMENSION)
        low, high = self._BRIGHTNESS_RANGE
        midpoint = (low + high) / 2
        brightness_score = 1.0 if low <= brightness <= high else max(0.0, 1.0 - abs(brightness - midpoint) / 128)

        quality = round(blur_score * 0.5 + resolution_score * 0.3 + brightness_score * 0.2, 4)
        return {
            "quality": quality,
            "blur_variance": round(blur_variance, 2),
            "width": width,
            "height": height,
            "brightness": round(brightness, 2),
        }
