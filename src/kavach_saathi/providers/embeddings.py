from __future__ import annotations

from kavach_saathi.config import Settings


class TextEmbedder:
    """Self-hosted sentence embeddings (no API key required) used to build the RAG
    context for Agent 3 (final target plan.md Section 6) and Agent 5's grounding.
    """

    _model = None

    def __init__(self, settings: Settings):
        self.settings = settings

    @classmethod
    def _load(cls, model_name: str) -> None:
        if cls._model is not None:
            return
        from sentence_transformers import SentenceTransformer

        cls._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._load(self.settings.embedding_model)
        vectors = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    @property
    def dimension(self) -> int:
        self._load(self.settings.embedding_model)
        return self._model.get_sentence_embedding_dimension()
