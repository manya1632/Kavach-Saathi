from __future__ import annotations

import threading

from kavach_saathi.config import Settings


class TextEmbedder:
    """Self-hosted sentence embeddings (no API key required) used to build the RAG
    context for Agent 3 (final target plan.md Section 6) and Agent 5's grounding.
    """

    _model = None
    _load_lock = threading.Lock()

    def __init__(self, settings: Settings):
        self.settings = settings

    @classmethod
    def _load(cls, settings: Settings) -> None:
        from kavach_saathi.model_registry import get_sentence_transformer
        cls._model = get_sentence_transformer(settings)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._load(self.settings)
        vectors = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    @property
    def dimension(self) -> int:
        self._load(self.settings)
        return self._model.get_sentence_embedding_dimension()
