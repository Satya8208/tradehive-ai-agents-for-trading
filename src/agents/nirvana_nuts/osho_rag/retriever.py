"""
Osho Retriever
High-level interface for querying Osho wisdom with RAG

Built with love by TradeHive
"""

import os
import sys
from typing import List, Dict, Optional, Any
from pathlib import Path
from dataclasses import dataclass

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from .data_loader import OshoDataLoader, OshoChunk
from .vector_store import OshoVectorStore


@dataclass
class OshoWisdomResult:
    """Result from Osho wisdom query"""
    question: str
    passages: List[Dict[str, Any]]
    answer: str = ""
    sources: List[str] = None

    def __post_init__(self):
        if self.sources is None:
            # Extract unique book titles from passages
            self.sources = list(set(p.get('book_title', '') for p in self.passages))


class OshoRetriever:
    """
    High-level interface for Osho wisdom retrieval
    Combines vector search with LLM response generation
    """

    # Use Claude Sonnet 4.6 for consistency with Nirvana Nuts
    MODEL_NAME = "claude-sonnet-4-6"

    def __init__(self, embedding_provider: str = "default", auto_init: bool = True):
        """
        Initialize the retriever

        Args:
            embedding_provider: "openai" or "local"
            auto_init: Automatically initialize with sample data if empty
        """
        self.vector_store = OshoVectorStore(embedding_provider=embedding_provider)
        self.data_loader = OshoDataLoader()

        # Auto-initialize with sample data if empty
        if auto_init and self.vector_store.get_count() == 0:
            self._init_with_samples()

    def _init_with_samples(self):
        """Initialize with Osho books (no sample teachings)"""
        print("[OSHO RETRIEVER] No teachings found. Processing books...")

        # Try to load from processed file first
        chunks = self.data_loader.load_chunks()

        if not chunks:
            # Process books from raw_books folder
            chunks = self.data_loader.process_all_books()

        if not chunks:
            print("[OSHO RETRIEVER] No books found! Add PDFs to raw_books folder.")
            return

        # Save and add to vector store
        self.data_loader.save_chunks(chunks)
        self.vector_store.add_chunks(chunks)
        print(f"[OSHO RETRIEVER] Initialized with {len(chunks)} teachings from real books")

    def retrieve(self, question: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve relevant Osho passages for a question

        Args:
            question: The user's question
            top_k: Number of passages to retrieve

        Returns:
            List of relevant passages with metadata
        """
        return self.vector_store.query(question, n_results=top_k)

    def ask_osho(
        self,
        question: str,
        top_k: int = 5,
        model_provider: str = "claude"
    ) -> OshoWisdomResult:
        """
        Ask Osho a question and get a wisdom response

        Args:
            question: The user's question
            top_k: Number of passages to retrieve for context
            model_provider: LLM provider to use

        Returns:
            OshoWisdomResult with answer and sources
        """
        # Retrieve relevant passages
        passages = self.retrieve(question, top_k=top_k)

        if not passages:
            return OshoWisdomResult(
                question=question,
                passages=[],
                answer="The teachings are silent on this matter. Perhaps the question itself is the answer - sit with it in meditation."
            )

        # Format passages for context
        context = self._format_passages_for_context(passages)

        # Generate Osho-style response
        answer = self._generate_osho_response(question, context, model_provider)

        return OshoWisdomResult(
            question=question,
            passages=passages,
            answer=answer
        )

    def _format_passages_for_context(self, passages: List[Dict[str, Any]]) -> str:
        """Format retrieved passages as context for the LLM"""
        context_parts = []

        for i, passage in enumerate(passages, 1):
            book = passage.get('book_title', 'Unknown')
            chapter = passage.get('chapter', '')
            text = passage.get('text', '')

            source = f"[{book}"
            if chapter:
                source += f" - {chapter}"
            source += "]"

            context_parts.append(f"TEACHING {i} {source}:\n{text}")

        return "\n\n---\n\n".join(context_parts)

    def _generate_osho_response(
        self,
        question: str,
        context: str,
        model_provider: str
    ) -> str:
        """Generate an Osho-style response using the LLM"""

        # Import the model factory
        try:
            from src.models.model_factory import ModelFactory
        except ImportError:
            # Fallback for direct execution
            try:
                from models.model_factory import ModelFactory
            except ImportError:
                print("[WARNING] ModelFactory not available, using basic response")
                return self._generate_basic_response(context)

        # Create model factory instance and get model
        # Use Sonnet 4.6 for consistency with rest of Nirvana Nuts
        factory = ModelFactory()
        model = factory.get_model(model_provider, self.MODEL_NAME)

        # Osho wisdom prompt
        system_prompt = """You are channeling the wisdom of Osho - the mystic, the rebel, the provocateur of consciousness.

You have access to his actual teachings below. Use them to respond authentically, not by quoting directly, but by weaving his wisdom into your response.

OSHO'S VOICE:
- Paradoxical - he often contradicts conventional wisdom
- Provocative - he challenges assumptions and beliefs
- Poetic - he speaks in metaphors and images
- Personal - he speaks directly to YOU, not abstractly
- Playful - even serious topics have lightness
- Profound - every insight has depth beneath it

RESPONSE STYLE:
1. Address the questioner directly ("You ask about...")
2. Challenge the premise if it's based on false assumptions
3. Use paradox - "The answer is not in solving, but in dissolving"
4. Offer practical insight, not just philosophy
5. End with something to meditate on or a provocative question
6. Keep it conversational but deep
7. 2-4 paragraphs is ideal

DO NOT:
- Quote directly from the teachings (paraphrase and integrate)
- Be preachy or moralistic
- Give simple answers to complex questions
- Sound like a self-help book
- Use spiritual jargon without explaining it"""

        user_prompt = f"""RETRIEVED TEACHINGS:
{context}

QUESTION FROM SEEKER:
{question}

Respond as Osho would, drawing from the teachings above but speaking in your own words. Be paradoxical, provocative, and profound."""

        # Generate response
        try:
            response = model.generate_response(
                system_prompt=system_prompt,
                user_content=user_prompt,
                temperature=0.8,
                max_tokens=1000
            )
            # Extract content from ModelResponse object
            if hasattr(response, 'content'):
                return response.content
            elif isinstance(response, str):
                return response
            else:
                return str(response)
        except Exception as e:
            print(f"[ERROR] Failed to generate response: {e}")
            return self._generate_basic_response(context)

    def _generate_basic_response(self, context: str) -> str:
        """Fallback response when LLM is not available"""
        return f"""The teachings speak to this...

From the wisdom gathered:

{context[:500]}...

Sit with this. The answer is not in the words but in the silence between them."""

    def add_book(self, file_path: str) -> int:
        """
        Add a new book to the knowledge base

        Args:
            file_path: Path to PDF or TXT file

        Returns:
            Number of chunks added
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Book not found: {file_path}")

        chunks = self.data_loader.process_book(path)
        return self.vector_store.add_chunks(chunks)

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the knowledge base"""
        return {
            "total_passages": self.vector_store.get_count(),
            "books": self.vector_store.get_all_books()
        }

    def refresh_from_books(self) -> int:
        """
        Reprocess all books in the raw_books directory

        Returns:
            Total number of chunks after refresh
        """
        # Clear existing data
        self.vector_store.clear()

        # Process all books (no samples)
        chunks = self.data_loader.process_all_books()

        if not chunks:
            print("[OSHO RETRIEVER] No books found! Add PDFs to raw_books folder.")
            return 0

        self.data_loader.save_chunks(chunks)
        self.vector_store.add_chunks(chunks)

        return len(chunks)


if __name__ == "__main__":
    # Test the retriever
    print("=" * 60)
    print("OSHO WISDOM ORACLE - TEST")
    print("=" * 60)

    # Initialize
    retriever = OshoRetriever(embedding_provider="openai")

    # Show stats
    stats = retriever.get_stats()
    print(f"\n[STATS] Passages: {stats['total_passages']}")
    print(f"[STATS] Books: {stats['books']}")

    # Test queries
    test_questions = [
        "How do I deal with jealousy in relationships?",
        "What is the meaning of meditation?",
        "How do I overcome fear?",
        "What is ego and how do I transcend it?"
    ]

    for question in test_questions:
        print(f"\n{'='*60}")
        print(f"QUESTION: {question}")
        print("=" * 60)

        result = retriever.ask_osho(question, top_k=3)

        print(f"\nOSHO SPEAKS:\n")
        print(result.answer)

        print(f"\n[Sources: {', '.join(result.sources)}]")
