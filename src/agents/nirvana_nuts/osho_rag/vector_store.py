"""
Osho Vector Store
ChromaDB wrapper for storing and querying Osho teachings

Built with love by TradeHive
"""

import os
from typing import List, Dict, Optional, Any
from pathlib import Path

from .data_loader import OshoChunk
from .embeddings import OshoEmbeddings


class OshoVectorStore:
    """
    ChromaDB-based vector store for Osho teachings
    Stores embeddings and metadata for semantic search
    """

    COLLECTION_NAME = "osho_teachings"

    def __init__(self, persist_dir: Optional[str] = None, embedding_provider: str = "default"):
        """
        Initialize the vector store

        Args:
            persist_dir: Directory to persist ChromaDB data
            embedding_provider: "default" (ChromaDB built-in), "openai", or "local"
        """
        if persist_dir is None:
            project_root = Path(__file__).parent.parent.parent.parent.parent
            persist_dir = str(project_root / "src" / "data" / "nirvana_nuts" / "osho_knowledge" / "chroma_db")

        self.persist_dir = persist_dir
        self.embedding_provider = embedding_provider

        # Only initialize external embeddings if not using default
        if embedding_provider != "default":
            self.embeddings = OshoEmbeddings(provider=embedding_provider)
        else:
            self.embeddings = None

        # Initialize ChromaDB
        self._init_chroma()

    def _init_chroma(self):
        """Initialize ChromaDB client and collection"""
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            raise ImportError("chromadb not installed. Run: pip install chromadb")

        # Use persistent storage
        self.client = chromadb.PersistentClient(path=self.persist_dir)

        # Get or create collection - use default embeddings (all-MiniLM-L6-v2 built into ChromaDB)
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "Osho teachings and wisdom"}
        )

        print(f"[VECTOR STORE] Initialized with {self.collection.count()} documents")

    def add_chunks(self, chunks: List[OshoChunk]) -> int:
        """
        Add chunks to the vector store

        Returns:
            Number of chunks added
        """
        if not chunks:
            return 0

        # Prepare data
        ids = [chunk.chunk_id for chunk in chunks]
        texts = [chunk.text for chunk in chunks]
        metadatas = [
            {
                "book_title": chunk.book_title,
                "chapter": chunk.chapter,
                "page": chunk.page
            }
            for chunk in chunks
        ]

        # Check for existing IDs to avoid duplicates
        existing = set()
        try:
            result = self.collection.get(ids=ids)
            if result and result['ids']:
                existing = set(result['ids'])
        except:
            pass

        # Filter out existing
        new_indices = [i for i, id in enumerate(ids) if id not in existing]

        if not new_indices:
            print("[VECTOR STORE] All chunks already exist")
            return 0

        new_ids = [ids[i] for i in new_indices]
        new_texts = [texts[i] for i in new_indices]
        new_metadatas = [metadatas[i] for i in new_indices]

        print(f"[VECTOR STORE] Creating embeddings for {len(new_texts)} chunks...")

        # Use ChromaDB's default embeddings or external embeddings
        if self.embedding_provider == "default" or self.embeddings is None:
            # Let ChromaDB create embeddings automatically (uses all-MiniLM-L6-v2)
            self.collection.add(
                ids=new_ids,
                documents=new_texts,
                metadatas=new_metadatas
            )
        else:
            # Use external embeddings
            embeddings = self.embeddings.embed_texts(new_texts)
            self.collection.add(
                ids=new_ids,
                embeddings=embeddings,
                documents=new_texts,
                metadatas=new_metadatas
            )

        print(f"[VECTOR STORE] Added {len(new_ids)} chunks")
        return len(new_ids)

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        book_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Query the vector store for relevant passages

        Args:
            query_text: The question or query
            n_results: Number of results to return
            book_filter: Optional filter by book title

        Returns:
            List of matching passages with metadata
        """
        # Build where clause for filtering
        where = None
        if book_filter:
            where = {"book_title": {"$eq": book_filter}}

        # Query collection - use query_texts for default embeddings, query_embeddings for custom
        if self.embedding_provider == "default" or self.embeddings is None:
            # Let ChromaDB handle embedding the query
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"]
            )
        else:
            # Use external embeddings
            query_embedding = self.embeddings.embed_text(query_text)
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"]
            )

        # Format results
        formatted = []
        if results and results['documents'] and results['documents'][0]:
            for i, doc in enumerate(results['documents'][0]):
                formatted.append({
                    "text": doc,
                    "book_title": results['metadatas'][0][i].get('book_title', ''),
                    "chapter": results['metadatas'][0][i].get('chapter', ''),
                    "distance": results['distances'][0][i] if results['distances'] else 0,
                    "relevance_score": 1 - (results['distances'][0][i] if results['distances'] else 0)
                })

        return formatted

    def get_all_books(self) -> List[str]:
        """Get list of all book titles in the store"""
        # Get all metadata
        result = self.collection.get(include=["metadatas"])

        if not result or not result['metadatas']:
            return []

        books = set()
        for metadata in result['metadatas']:
            if 'book_title' in metadata:
                books.add(metadata['book_title'])

        return sorted(list(books))

    def get_count(self) -> int:
        """Get total number of documents in the store"""
        return self.collection.count()

    def clear(self):
        """Clear all documents from the store"""
        self.client.delete_collection(self.COLLECTION_NAME)
        self.collection = self.client.create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "Osho teachings and wisdom"}
        )
        print("[VECTOR STORE] Cleared all documents")


if __name__ == "__main__":
    # Test the vector store
    print("[TEST] Testing OshoVectorStore...")

    store = OshoVectorStore()
    print(f"[TEST] Documents in store: {store.get_count()}")

    if store.get_count() == 0:
        # Add sample data
        from .data_loader import OshoDataLoader
        loader = OshoDataLoader()
        chunks = loader.add_sample_teachings()
        store.add_chunks(chunks)

    # Test query
    results = store.query("How do I deal with anger?", n_results=3)

    print("\n[TEST] Query: 'How do I deal with anger?'")
    print("[TEST] Results:")
    for i, result in enumerate(results, 1):
        print(f"\n  {i}. [{result['book_title']}] (score: {result['relevance_score']:.3f})")
        print(f"     {result['text'][:200]}...")

    print("\n[TEST] Books in store:", store.get_all_books())
