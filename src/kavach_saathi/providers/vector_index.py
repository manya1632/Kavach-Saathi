from __future__ import annotations

from typing import Any

from kavach_saathi.config import Settings
from kavach_saathi.providers.embeddings import TextEmbedder


class PineconeUnavailable(RuntimeError):
    pass


class PineconeIndex:
    """Thin wrapper over a single Pinecone index, shared by Agent 3 (cross-seller size
    RAG) and Agent 5 (voice Q&A grounding + learning loop) per final target plan.md
    Section 6. Real vector upsert/query -- no fixture shortcut.
    """

    _clients: dict[str, Any] = {}

    def __init__(self, settings: Settings, *, index_name: str):
        self.settings = settings
        self.index_name = index_name
        self.embedder = TextEmbedder(settings)

    def _index(self):
        if not self.settings.pinecone_api_key:
            raise PineconeUnavailable("PINECONE_API_KEY is not configured")
        cache_key = f"{self.settings.pinecone_api_key}:{self.index_name}"
        if cache_key in self._clients:
            return self._clients[cache_key]

        from pinecone import Pinecone, ServerlessSpec

        pc = Pinecone(api_key=self.settings.pinecone_api_key)
        existing = set(pc.list_indexes().names())
        if self.index_name not in existing:
            pc.create_index(
                name=self.index_name,
                dimension=self.embedder.dimension,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region=self.settings.pinecone_environment or "us-east-1"),
            )
        index = pc.Index(self.index_name)
        self._clients[cache_key] = index
        return index

    def upsert(self, records: list[dict[str, Any]], *, namespace: str) -> None:
        """records: [{"id": str, "text": str, "metadata": dict}, ...]"""
        if not records:
            return
        index = self._index()
        vectors = self.embedder.embed([r["text"] for r in records])
        payload = [
            {"id": record["id"], "values": vector, "metadata": {**record.get("metadata", {}), "text": record["text"]}}
            for record, vector in zip(records, vectors, strict=True)
        ]
        index.upsert(vectors=payload, namespace=namespace)

    def query(
        self, text: str, *, namespace: str, top_k: int = 5, filter: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        index = self._index()
        vector = self.embedder.embed_one(text)
        response = index.query(
            vector=vector, top_k=top_k, namespace=namespace, filter=filter, include_metadata=True
        )
        # The Pinecone SDK's QueryResponse supports both attribute and dict-style
        # access depending on version; support either rather than assume one.
        matches = response["matches"] if isinstance(response, dict) else response.matches
        results = []
        for match in matches:
            match_id = match["id"] if isinstance(match, dict) else match.id
            score = match["score"] if isinstance(match, dict) else match.score
            metadata = (match["metadata"] if isinstance(match, dict) else match.metadata) or {}
            results.append({"id": match_id, "score": score, **metadata})
        return results
