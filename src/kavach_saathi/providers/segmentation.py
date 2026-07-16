from __future__ import annotations

import io
import threading

from kavach_saathi.config import Settings

_SAM2_CHECKPOINT = "facebook/sam2.1-hiera-tiny"


class GarmentSegmenter:
    """SAM 2.0 garment segmentation (final target plan.md Section 6, Agent 1 step (a)).

    Self-hosted via `transformers`' SAM2 support — no API key required. The model is
    lazy-loaded once per process (first call downloads the checkpoint from the HF Hub).
    """

    _model = None
    _processor = None
    _load_lock = threading.Lock()

    def __init__(self, settings: Settings | None = None):
        self.settings = settings

    @classmethod
    def _load(cls) -> None:
        if cls._model is not None:
            return
        # Listing analysis runs Agents 1 and 2 concurrently and both use this
        # segmenter. Two simultaneous `from_pretrained` calls can expose a
        # half-initialized Accelerate model whose weights are still on the `meta`
        # device. Load into locals under a process-wide lock and publish the pair
        # only after every tensor is materialized on CPU.
        with cls._load_lock:
            if cls._model is not None:
                return
            from transformers import Sam2Model, Sam2Processor

            model = Sam2Model.from_pretrained(
                _SAM2_CHECKPOINT,
                device_map=None,
                low_cpu_mem_usage=False,
            )
            processor = Sam2Processor.from_pretrained(_SAM2_CHECKPOINT)
            model.to("cpu")
            model.eval()
            cls._processor = processor
            cls._model = model

    def segment(self, image_bytes: bytes) -> bytes:
        """Return a PNG of the input image with the background alpha-masked out,
        isolating the garment SAM 2.0 identifies at the image's center point."""
        self._load()

        import numpy as np
        import torch
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        width, height = image.size
        # A center-point prompt is a reasonable deterministic heuristic for "the product"
        # in a seller-uploaded flat-lay or single-garment catalogue photo.
        input_points = [[[[width // 2, height // 2]]]]
        input_labels = [[[1]]]
        inputs = self._processor(
            images=image, input_points=input_points, input_labels=input_labels, return_tensors="pt"
        )
        with torch.no_grad():
            outputs = self._model(**inputs)
        masks = self._processor.post_process_masks(outputs.pred_masks, inputs["original_sizes"])
        scores = outputs.iou_scores[0][0]
        best_index = int(torch.argmax(scores).item())
        mask = masks[0][0][best_index].numpy()

        rgba = image.convert("RGBA")
        alpha = (np.asarray(mask, dtype=np.uint8) * 255).astype(np.uint8)
        alpha_image = Image.fromarray(alpha, mode="L").resize(rgba.size)
        rgba.putalpha(alpha_image)
        buffer = io.BytesIO()
        rgba.save(buffer, format="PNG")
        return buffer.getvalue()
