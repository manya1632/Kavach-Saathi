from __future__ import annotations

import io

_CLIP_CHECKPOINT = "openai/clip-vit-base-patch32"


class ReturnVisionVerifier:
    """Agent 8's real CV pipeline (final target plan.md Section 6): extracts frames
    from the buyer's return video and compares them against the product's real
    catalogue image via CLIP *and* ResNet-50 embedding similarity -- two
    independent models cross-checking each other, the same pattern Agent 2 uses for
    fabric/color -- replacing the previous `expected_confidence` fixture override
    entirely. Both self-hosted, open-weight -- no API key required.
    """

    _clip_model = None
    _clip_processor = None
    _resnet_model = None
    _resnet_transform = None

    @classmethod
    def _load_clip(cls) -> None:
        if cls._clip_model is not None:
            return
        from transformers import CLIPModel, CLIPProcessor

        cls._clip_model = CLIPModel.from_pretrained(_CLIP_CHECKPOINT)
        cls._clip_processor = CLIPProcessor.from_pretrained(_CLIP_CHECKPOINT)
        cls._clip_model.eval()

    @classmethod
    def _load_resnet(cls) -> None:
        if cls._resnet_model is not None:
            return
        import torch
        from torchvision.models import ResNet50_Weights, resnet50

        weights = ResNet50_Weights.IMAGENET1K_V2
        model = resnet50(weights=weights)
        model.fc = torch.nn.Identity()  # drop the classification head -- we want the pooled feature embedding
        model.eval()
        cls._resnet_model = model
        cls._resnet_transform = weights.transforms()

    def extract_frames(self, video_bytes: bytes, *, count: int = 5) -> list[bytes]:
        """Evenly-spaced JPEG frames sampled across the video's duration via OpenCV."""
        import os
        import tempfile

        import cv2

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            handle.write(video_bytes)
            temp_path = handle.name
        try:
            capture = cv2.VideoCapture(temp_path)
            total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames <= 0:
                capture.release()
                return []
            indices = sorted({int(total_frames * (i + 1) / (count + 1)) for i in range(count)})
            frames: list[bytes] = []
            for index in indices:
                capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, frame = capture.read()
                if not ok:
                    continue
                ok, buffer = cv2.imencode(".jpg", frame)
                if ok:
                    frames.append(buffer.tobytes())
            capture.release()
            return frames
        finally:
            os.unlink(temp_path)

    def _clip_embedding(self, image_bytes: bytes):
        import torch
        from PIL import Image

        self._load_clip()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        inputs = self._clip_processor(images=image, return_tensors="pt")
        with torch.no_grad():
            embedding = self._clip_model.get_image_features(**inputs)
        return embedding / embedding.norm(dim=-1, keepdim=True)

    def _resnet_embedding(self, image_bytes: bytes):
        import torch
        from PIL import Image

        self._load_resnet()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        batch = self._resnet_transform(image).unsqueeze(0)
        with torch.no_grad():
            embedding = self._resnet_model(batch)
        return embedding / embedding.norm(dim=-1, keepdim=True)

    def best_match(self, candidate_frames: list[bytes], reference_image_bytes: bytes) -> tuple[float, bytes | None]:
        """Combined CLIP + ResNet-50 cosine similarity (averaged) between the
        reference catalogue image and each candidate frame; returns the best-matching
        frame and its score so the caller can also run OCR on the frame most likely to
        show the label clearly, rather than an arbitrary one. Averaging two
        independent embedding spaces means a coincidental high score in one model
        alone isn't enough to call it a match.
        """
        if not candidate_frames:
            return 0.0, None
        reference_clip = self._clip_embedding(reference_image_bytes)
        reference_resnet = self._resnet_embedding(reference_image_bytes)
        best_score = -1.0
        best_frame: bytes | None = None
        for frame in candidate_frames:
            clip_score = float((reference_clip @ self._clip_embedding(frame).T).item())
            resnet_score = float((reference_resnet @ self._resnet_embedding(frame).T).item())
            score = (clip_score + resnet_score) / 2
            if score > best_score:
                best_score = score
                best_frame = frame
        return best_score, best_frame
