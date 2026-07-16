from __future__ import annotations

import io

from kavach_saathi.providers.segmentation import GarmentSegmenter

FABRIC_LABELS = [
    "cotton fabric",
    "polyester fabric",
    "silk fabric",
    "denim fabric",
    "wool fabric",
    "linen fabric",
    "viscose fabric",
    "leather",
    "chiffon fabric",
    "velvet fabric",
    "knit fabric",
    "synthetic blend fabric",
]

_CLIP_CHECKPOINT = "openai/clip-vit-base-patch32"

# ImageNet class names that are actual fabric/material categories -- used as a second,
# independent CV signal (ResNet-50) alongside CLIP's zero-shot fabric classification.
_RESNET_FABRIC_CLASSES = {
    "wool",
    "velvet",
    "denim",
    "corduroy",
    "knit",
    "cardigan",
    "sweatshirt",
    "jersey",
    "sarong",
    "kimono",
}


class FabricVisionClassifier:
    """Agent 2 step 2: CV classifier (CLIP + ResNet-50) independently infers
    fabric/color from the garment image, for cross-checking against Claude's OCR
    extraction (final target plan.md Section 6, Agent 2). Both models are self-hosted,
    open-weight -- no API key required.
    """

    _clip_model = None
    _clip_processor = None
    _resnet_model = None
    _resnet_categories = None
    _resnet_transform = None

    @classmethod
    def _load_clip(cls) -> None:
        if cls._clip_model is not None:
            return
        from kavach_saathi.config import get_settings
        from kavach_saathi.model_registry import get_clip
        cls._clip_model, cls._clip_processor = get_clip(get_settings())

    @classmethod
    def _load_resnet(cls) -> None:
        if cls._resnet_model is not None:
            return
        from kavach_saathi.model_registry import get_resnet
        weights, model = get_resnet()
        cls._resnet_model = model
        cls._resnet_categories = weights.meta["categories"]
        cls._resnet_transform = weights.transforms()

    def _clip_fabric_guess(self, image) -> tuple[str, float]:
        import torch

        self._load_clip()
        inputs = self._clip_processor(text=FABRIC_LABELS, images=image, return_tensors="pt", padding=True)
        with torch.no_grad():
            outputs = self._clip_model(**inputs)
        probs = outputs.logits_per_image.softmax(dim=1)[0]
        best_index = int(torch.argmax(probs).item())
        return FABRIC_LABELS[best_index].removesuffix(" fabric"), float(probs[best_index].item())

    def _resnet_top_labels(self, image) -> list[dict]:
        import torch

        self._load_resnet()
        batch = self._resnet_transform(image).unsqueeze(0)
        with torch.no_grad():
            logits = self._resnet_model(batch)
        probs = logits.softmax(dim=1)[0]
        top_probs, top_indices = torch.topk(probs, 5)
        return [
            {"label": self._resnet_categories[int(index)], "confidence": float(prob)}
            for prob, index in zip(top_probs, top_indices, strict=True)
        ]

    def _dominant_color_hex(self, image_bytes: bytes) -> str:
        # Reuse Agent 1's SAM 2.0 segmenter to isolate the garment before sampling
        # color -- a whole-frame average is dominated by background/card chrome, so
        # this is the only reliable way to get the garment's actual color.
        segmented_png = GarmentSegmenter().segment(image_bytes)

        from PIL import Image

        rgba = Image.open(io.BytesIO(segmented_png)).convert("RGBA")
        small = rgba.resize((48, 48))
        pixels = [p for p in small.getdata() if p[3] > 128]  # opaque (garment) pixels only
        if not pixels:
            pixels = list(small.getdata())
        # Bucket into 4-bit-per-channel cells and take the most frequent cell's mean
        # color. Real pixel-level CV, not a model call, but genuinely computed from the
        # segmented garment rather than guessed.
        buckets: dict[tuple[int, int, int], list[tuple[int, int, int]]] = {}
        for pixel in pixels:
            key = (pixel[0] // 16, pixel[1] // 16, pixel[2] // 16)
            buckets.setdefault(key, []).append(pixel[:3])
        largest = max(buckets.values(), key=len)
        r = sum(p[0] for p in largest) // len(largest)
        g = sum(p[1] for p in largest) // len(largest)
        b = sum(p[2] for p in largest) // len(largest)
        return f"#{r:02X}{g:02X}{b:02X}"

    def classify(self, image_bytes: bytes) -> dict:
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        clip_fabric, clip_confidence = self._clip_fabric_guess(image)
        resnet_labels = self._resnet_top_labels(image)
        resnet_fabric_hits = [
            item for item in resnet_labels if item["label"].lower() in _RESNET_FABRIC_CLASSES
        ]
        return {
            "clip_fabric": clip_fabric,
            "clip_confidence": round(clip_confidence, 4),
            "resnet_top_labels": resnet_labels,
            "resnet_fabric_hint": resnet_fabric_hits[0]["label"] if resnet_fabric_hits else None,
            "dominant_color_hex": self._dominant_color_hex(image_bytes),
        }


def hex_color_distance(a: str, b: str) -> float:
    """Euclidean RGB distance between two hex colors, normalized to 0-1."""
    a_rgb = tuple(int(a.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    b_rgb = tuple(int(b.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    distance = sum((x - y) ** 2 for x, y in zip(a_rgb, b_rgb, strict=True)) ** 0.5
    return distance / (255 * 3**0.5)
