"""Persistent Vector Index and Semantic Similarity Engine."""

import json
import math
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import aiosqlite
from logscope.storage.db import Database


class LocalVectorIndex:
    """Stores and searches semantic embeddings for templates, anomalies, and historical context."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        a = np.array(vec_a, dtype=np.float32)
        b = np.array(vec_b, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    @staticmethod
    def compute_local_tfidf_embedding(text: str, dim: int = 128) -> List[float]:
        """Fast offline feature vector fallback using character n-grams and hashing."""
        vec = np.zeros(dim, dtype=np.float32)
        tokens = text.lower().split()
        for token in tokens:
            # Hash token into dim buckets
            h = hash(token) % dim
            vec[h] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    async def add_record(
        self,
        text_content: str,
        embedding: Optional[List[float]] = None,
        template_id: Optional[str] = None,
        anomaly_id: Optional[str] = None
    ) -> str:
        """Stores a vector and text content in the embedding records table."""
        record_id = str(uuid.uuid4())
        if embedding is None:
            embedding = self.compute_local_tfidf_embedding(text_content)

        async with self.db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO embedding_records (id, template_id, anomaly_id, embedding_json, text_content)
                VALUES (?, ?, ?, ?, ?)
                """,
                (record_id, template_id, anomaly_id, json.dumps(embedding), text_content)
            )
            await conn.commit()
        return record_id

    async def search_similar(
        self,
        query_text: str,
        query_embedding: Optional[List[float]] = None,
        top_k: int = 5,
        min_score: float = 0.2
    ) -> List[Dict[str, Any]]:
        """Finds top-k most semantically similar historical records."""
        if query_embedding is None:
            query_embedding = self.compute_local_tfidf_embedding(query_text)

        async with self.db.get_connection() as conn:
            async with conn.execute(
                "SELECT id, template_id, anomaly_id, embedding_json, text_content, created_at FROM embedding_records"
            ) as cursor:
                rows = await cursor.fetchall()

        results = []
        for row in rows:
            try:
                emb = json.loads(row["embedding_json"])
                score = self._cosine_similarity(query_embedding, emb)
                if score >= min_score:
                    results.append({
                        "id": row["id"],
                        "template_id": row["template_id"],
                        "anomaly_id": row["anomaly_id"],
                        "text_content": row["text_content"],
                        "score": round(score, 4),
                        "created_at": row["created_at"]
                    })
            except Exception:
                continue

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    async def search_resolutions(
        self,
        query_text: str,
        query_embedding: Optional[List[float]] = None,
        top_k: int = 3,
        min_score: float = 0.25
    ) -> List[Dict[str, Any]]:
        """Finds top-k most similar past incident resolution knowledge records."""
        matches = await self.search_similar(
            query_text=query_text,
            query_embedding=query_embedding,
            top_k=top_k * 2,
            min_score=min_score
        )
        resolutions = [m for m in matches if "[Resolution Knowledge" in m["text_content"]]
        return resolutions[:top_k]

