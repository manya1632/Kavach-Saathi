from __future__ import annotations

import io

_CLIP_CHECKPOINT = "openai/clip-vit-base-patch32"
_BERT_CHECKPOINT = "bert-base-multilingual-cased"


class ReviewRelevanceClassifier:
    """Agent 4: Review Truth Filter's real CV/NLP pair (final target plan.md Section 6:
    "CLIP-based image-text relevance scoring; BERT multimodal classifier"). Both
    self-hosted, open-weight models -- no API key required, no `expected_relevant`
    fixture read.

    CLIP scores whether the review *photo* actually depicts the product it was left on.
    BERT (multilingual, since reviews arrive in Hindi/English/Hinglish) scores whether
    the review *text* is topically related to the product, independent of sentiment.
    """

    _clip_model = None
    _clip_processor = None
    _bert_model = None
    _bert_tokenizer = None

    @classmethod
    def _load_clip(cls) -> None:
        if cls._clip_model is not None:
            return
        from transformers import CLIPModel, CLIPProcessor

        cls._clip_model = CLIPModel.from_pretrained(_CLIP_CHECKPOINT)
        cls._clip_processor = CLIPProcessor.from_pretrained(_CLIP_CHECKPOINT)
        cls._clip_model.eval()

    @classmethod
    def _load_bert(cls) -> None:
        if cls._bert_model is not None:
            return
        from transformers import AutoModel, AutoTokenizer

        cls._bert_tokenizer = AutoTokenizer.from_pretrained(_BERT_CHECKPOINT)
        cls._bert_model = AutoModel.from_pretrained(_BERT_CHECKPOINT)
        cls._bert_model.eval()

    def _clip_image_text_similarity(self, image, text: str) -> float:
        import torch

        self._load_clip()
        inputs = self._clip_processor(text=[text], images=image, return_tensors="pt", padding=True)
        with torch.no_grad():
            outputs = self._clip_model(**inputs)
        image_embeds = outputs.image_embeds / outputs.image_embeds.norm(dim=-1, keepdim=True)
        text_embeds = outputs.text_embeds / outputs.text_embeds.norm(dim=-1, keepdim=True)
        return float((image_embeds @ text_embeds.T).item())

    def _bert_embed(self, text: str):
        import torch

        self._load_bert()
        tokens = self._bert_tokenizer(text, return_tensors="pt", truncation=True, max_length=128)
        with torch.no_grad():
            output = self._bert_model(**tokens)
        # Mean-pool token embeddings into one sentence-level vector.
        return output.last_hidden_state[0].mean(dim=0)

    def _bert_text_relevance(self, review_text: str, product_text: str) -> float:
        import torch

        review_vec = self._bert_embed(review_text)
        product_vec = self._bert_embed(product_text)
        return float(torch.nn.functional.cosine_similarity(review_vec, product_vec, dim=0).item())

    def classify(
        self,
        *,
        image_bytes: bytes | None,
        review_text: str,
        product_name: str,
        product_category: str,
    ) -> dict:
        product_text = f"{product_name}, {product_category}"

        text_relevance = self._bert_text_relevance(review_text, product_text) if review_text.strip() else None

        image_relevance = None
        if image_bytes:
            from PIL import Image

            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            image_relevance = self._clip_image_text_similarity(image, product_text)

        return {"clip_image_text_similarity": image_relevance, "bert_text_relevance": text_relevance}
