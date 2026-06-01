"""
Osho Embeddings
Create embeddings for Osho text chunks

Built with love by TradeHive
"""

import os
from typing import List, Optional
from pathlib import Path


class OshoEmbeddings:
    """
    Create embeddings for Osho text chunks
    Supports OpenAI embeddings or local alternatives
    """

    def __init__(self, provider: str = "openai"):
        """
        Initialize embeddings provider

        Args:
            provider: "openai" or "local" (sentence-transformers)
        """
        self.provider = provider
        self._model = None
        self._openai_client = None

    def _init_openai(self):
        """Initialize OpenAI client"""
        if self._openai_client is None:
            try:
                from openai import OpenAI
                api_key = os.getenv("OPENAI_KEY") or os.getenv("OPENAI_API_KEY")

                if not api_key:
                    raise ValueError("OPENAI_KEY not found in environment")

                self._openai_client = OpenAI(api_key=api_key)
            except ImportError:
                raise ImportError("openai package not installed. Run: pip install openai")

        return self._openai_client

    def _init_local(self):
        """Initialize local sentence-transformers model"""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                # Use a lightweight but effective model
                self._model = SentenceTransformer('all-MiniLM-L6-v2')
            except ImportError:
                raise ImportError("sentence-transformers not installed. Run: pip install sentence-transformers")

        return self._model

    def embed_text(self, text: str) -> List[float]:
        """Create embedding for a single text"""
        if self.provider == "openai":
            client = self._init_openai()
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=text
            )
            return response.data[0].embedding
        else:
            model = self._init_local()
            embedding = model.encode(text)
            return embedding.tolist()

    def embed_texts(self, texts: List[str], batch_size: int = 100) -> List[List[float]]:
        """Create embeddings for multiple texts"""
        if self.provider == "openai":
            client = self._init_openai()

            all_embeddings = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                response = client.embeddings.create(
                    model="text-embedding-3-small",
                    input=batch
                )
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)

                if len(texts) > batch_size:
                    print(f"[EMBEDDINGS] Processed {min(i + batch_size, len(texts))}/{len(texts)} texts")

            return all_embeddings
        else:
            model = self._init_local()
            embeddings = model.encode(texts, show_progress_bar=len(texts) > 10)
            return embeddings.tolist()

    @property
    def dimension(self) -> int:
        """Get embedding dimension"""
        if self.provider == "openai":
            return 1536  # text-embedding-3-small dimension
        else:
            return 384  # all-MiniLM-L6-v2 dimension


if __name__ == "__main__":
    # Test embeddings
    print("[TEST] Testing OshoEmbeddings...")

    # Try OpenAI first, fall back to local
    try:
        embedder = OshoEmbeddings(provider="openai")
        embedding = embedder.embed_text("What is meditation?")
        print(f"[TEST] OpenAI embedding dimension: {len(embedding)}")
    except Exception as e:
        print(f"[TEST] OpenAI failed: {e}")
        print("[TEST] Trying local embeddings...")

        embedder = OshoEmbeddings(provider="local")
        embedding = embedder.embed_text("What is meditation?")
        print(f"[TEST] Local embedding dimension: {len(embedding)}")

    print("[TEST] Embeddings working!")
