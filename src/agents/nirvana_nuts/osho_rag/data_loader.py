"""
Osho Data Loader
Load and process Osho books/discourses into chunks for embedding

Built with love by TradeHive
"""

import os
import re
import json
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict


@dataclass
class OshoChunk:
    """A chunk of Osho text with metadata"""
    text: str
    book_title: str
    chapter: str = ""
    page: int = 0
    chunk_id: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


class OshoDataLoader:
    """
    Load and process Osho books from PDF/TXT files
    Chunks text into ~500-1000 character passages
    """

    # Priority books to load first
    PRIORITY_BOOKS = [
        "The Book of Secrets",
        "Courage: The Joy of Living Dangerously",
        "Awareness: The Key to Living in Balance",
        "The Mustard Seed",
        "Tao: The Three Treasures",
        "The Heart Sutra",
        "Zen: The Path of Paradox",
        "The Book of Wisdom",
        "Intimacy: Trusting Oneself and the Other",
        "Love, Freedom, Aloneness"
    ]

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            # Default to project data directory
            project_root = Path(__file__).parent.parent.parent.parent.parent
            data_dir = project_root / "src" / "data" / "nirvana_nuts" / "osho_knowledge"

        self.data_dir = Path(data_dir)
        self.raw_books_dir = self.data_dir / "raw_books"
        self.processed_dir = self.data_dir / "processed"

        # Ensure directories exist
        self.raw_books_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

        # Chunk settings
        self.chunk_size = 800  # Target chunk size in characters
        self.chunk_overlap = 100  # Overlap between chunks

    def load_pdf(self, pdf_path: Path) -> str:
        """Extract text from a PDF file"""
        try:
            import pdfplumber

            text = ""
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n\n"
            return text

        except ImportError:
            # Fallback to PyPDF2
            try:
                from PyPDF2 import PdfReader

                reader = PdfReader(pdf_path)
                text = ""
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n\n"
                return text

            except ImportError:
                print("[WARNING] Neither pdfplumber nor PyPDF2 installed. Install with: pip install pdfplumber")
                return ""

    def load_txt(self, txt_path: Path) -> str:
        """Load text from a TXT file"""
        with open(txt_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    def clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        # Remove multiple spaces
        text = re.sub(r' +', ' ', text)
        # Remove multiple newlines (keep max 2)
        text = re.sub(r'\n{3,}', '\n\n', text)
        # Fix common OCR issues
        text = text.replace('ﬁ', 'fi').replace('ﬂ', 'fl')
        # Remove page numbers and headers (common patterns)
        text = re.sub(r'^\d+\s*$', '', text, flags=re.MULTILINE)
        return text.strip()

    def chunk_text(self, text: str, book_title: str) -> List[OshoChunk]:
        """Split text into chunks with metadata"""
        chunks = []

        # First, try to split by chapters
        chapter_pattern = r'(Chapter\s+\d+|CHAPTER\s+\d+|Part\s+\d+|PART\s+\d+)'
        chapters = re.split(chapter_pattern, text)

        current_chapter = "Introduction"
        chunk_counter = 0

        for i, section in enumerate(chapters):
            # Check if this is a chapter header
            if re.match(chapter_pattern, section, re.IGNORECASE):
                current_chapter = section.strip()
                continue

            # Split section into paragraphs
            paragraphs = section.split('\n\n')
            current_chunk = ""

            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue

                # If adding this paragraph would exceed chunk size
                if len(current_chunk) + len(para) > self.chunk_size:
                    # Save current chunk if it has content
                    if len(current_chunk) >= 100:  # Min chunk size
                        chunk_counter += 1
                        chunks.append(OshoChunk(
                            text=current_chunk.strip(),
                            book_title=book_title,
                            chapter=current_chapter,
                            chunk_id=f"{book_title[:20]}_{chunk_counter}"
                        ))

                    # Start new chunk with overlap
                    if self.chunk_overlap > 0 and current_chunk:
                        # Keep last few sentences for context
                        overlap_text = current_chunk[-self.chunk_overlap:]
                        current_chunk = overlap_text + " " + para
                    else:
                        current_chunk = para
                else:
                    current_chunk += "\n\n" + para if current_chunk else para

            # Don't forget the last chunk
            if len(current_chunk) >= 100:
                chunk_counter += 1
                chunks.append(OshoChunk(
                    text=current_chunk.strip(),
                    book_title=book_title,
                    chapter=current_chapter,
                    chunk_id=f"{book_title[:20]}_{chunk_counter}"
                ))

        return chunks

    def process_book(self, file_path: Path) -> List[OshoChunk]:
        """Process a single book file (PDF or TXT)"""
        book_title = file_path.stem  # filename without extension

        print(f"[OSHO RAG] Processing: {book_title}")

        # Load based on file type
        if file_path.suffix.lower() == '.pdf':
            text = self.load_pdf(file_path)
        elif file_path.suffix.lower() == '.txt':
            text = self.load_txt(file_path)
        else:
            print(f"[WARNING] Unsupported file type: {file_path.suffix}")
            return []

        if not text:
            print(f"[WARNING] No text extracted from: {file_path}")
            return []

        # Clean and chunk
        text = self.clean_text(text)
        chunks = self.chunk_text(text, book_title)

        print(f"[OSHO RAG] Created {len(chunks)} chunks from {book_title}")

        return chunks

    def process_all_books(self) -> List[OshoChunk]:
        """Process all books in the raw_books directory"""
        all_chunks = []

        # Get all PDF and TXT files
        book_files = list(self.raw_books_dir.glob("*.pdf")) + list(self.raw_books_dir.glob("*.txt"))

        if not book_files:
            print(f"[OSHO RAG] No books found in: {self.raw_books_dir}")
            print("[OSHO RAG] Add PDF or TXT files of Osho books to get started")
            return []

        print(f"[OSHO RAG] Found {len(book_files)} books to process")

        for book_file in book_files:
            chunks = self.process_book(book_file)
            all_chunks.extend(chunks)

        # Save processed chunks
        self.save_chunks(all_chunks)

        print(f"[OSHO RAG] Total chunks created: {len(all_chunks)}")
        return all_chunks

    def save_chunks(self, chunks: List[OshoChunk], filename: str = "osho_chunks.json"):
        """Save processed chunks to JSON"""
        output_path = self.processed_dir / filename

        chunks_data = [chunk.to_dict() for chunk in chunks]

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(chunks_data, f, indent=2, ensure_ascii=False)

        print(f"[OSHO RAG] Saved chunks to: {output_path}")

    def load_chunks(self, filename: str = "osho_chunks.json") -> List[OshoChunk]:
        """Load previously processed chunks from JSON"""
        input_path = self.processed_dir / filename

        if not input_path.exists():
            return []

        with open(input_path, 'r', encoding='utf-8') as f:
            chunks_data = json.load(f)

        return [OshoChunk(**data) for data in chunks_data]

    def add_sample_teachings(self) -> List[OshoChunk]:
        """
        Add sample Osho teachings for testing
        These are paraphrased insights, not direct quotes
        """
        sample_teachings = [
            # On Meditation
            OshoChunk(
                text="Meditation is not about doing something, it is about undoing. It is not about achieving, but about letting go. When you sit silently, watching your breath, watching your thoughts without judgment, without trying to change anything - that is meditation. The mind wants to control, to manipulate, to achieve. But meditation is the exact opposite. It is surrender. It is saying yes to existence exactly as it is. In that acceptance, transformation happens on its own.",
                book_title="The Book of Secrets",
                chapter="Understanding Meditation",
                chunk_id="sample_meditation_1"
            ),
            OshoChunk(
                text="You ask how to meditate. But that very question comes from the achieving mind, the goal-oriented mind. Real meditation has no goal. It is not going anywhere. It is being here, totally here, utterly present. The present moment is the only door to the divine. The past is memory, the future is imagination - only the present is real. Drop into the present and you are in meditation.",
                book_title="The Book of Secrets",
                chapter="The Art of Presence",
                chunk_id="sample_meditation_2"
            ),

            # On Ego
            OshoChunk(
                text="The ego is not something real that you have to destroy. It is something unreal that you are believing in. Once you see its unreality, it disappears on its own. The ego is like darkness - you cannot fight with it, you cannot throw it out. Just bring in light and darkness disappears. Awareness is that light. When you become aware of your ego, when you watch it without identifying with it, it starts dissolving.",
                book_title="Awareness: The Key to Living in Balance",
                chapter="Understanding the Ego",
                chunk_id="sample_ego_1"
            ),
            OshoChunk(
                text="The ego always wants to be special - either specially good or specially bad. It does not matter. The ego can be very humble, and that becomes the ultimate ego. It can say 'I am the most humble person in the world' - and that is the greatest ego trip. Real humility is not knowing that you are humble. It is simply being natural, ordinary, with nothing to prove to anyone, not even to yourself.",
                book_title="Awareness: The Key to Living in Balance",
                chapter="The Game of Being Special",
                chunk_id="sample_ego_2"
            ),

            # On Love
            OshoChunk(
                text="Love is not about possessing someone. The moment you try to possess, love dies. Love is freedom - the freedom to be yourself, the freedom to let the other be themselves. When two freedoms meet, when two individuals meet without trying to dominate each other, that meeting is love. It is a dance of two flames, not a cage of two prisoners.",
                book_title="Love, Freedom, Aloneness",
                chapter="The Nature of Love",
                chunk_id="sample_love_1"
            ),
            OshoChunk(
                text="Most people think love means needing someone. But that is not love, that is dependency. Real love is not a need but an overflow. When you are so full of joy, so full of life, that you want to share it - that is love. A person who is empty inside, miserable inside, is always looking for someone to fill them. But no one else can fill you. First you have to be full, then love becomes a sharing, a celebration.",
                book_title="Love, Freedom, Aloneness",
                chapter="Love as Overflow",
                chunk_id="sample_love_2"
            ),

            # On Courage
            OshoChunk(
                text="Courage does not mean absence of fear. It means going ahead despite the fear. The coward also feels fear, the courageous also feels fear - the difference is that the coward listens to the fear, follows the fear, while the courageous acknowledges the fear but does not let it stop him. Every time you go beyond your fear, you grow. Fear is the opportunity for growth.",
                book_title="Courage: The Joy of Living Dangerously",
                chapter="Understanding Fear",
                chunk_id="sample_courage_1"
            ),
            OshoChunk(
                text="The greatest courage is to be yourself. The world constantly tells you what to be, how to be. Your parents, your teachers, your society - everyone has a model for you. But your soul has its own destiny. To follow your inner voice when the whole world is telling you to do something else - that is real courage. It is easy to follow the crowd. The path of the individual is the path of courage.",
                book_title="Courage: The Joy of Living Dangerously",
                chapter="Being Authentic",
                chunk_id="sample_courage_2"
            ),

            # On Awareness
            OshoChunk(
                text="Awareness is not thinking about something. Thinking is content-oriented, awareness is contentless. When you are thinking, you are identified with your thoughts. When you are aware, you are watching your thoughts from a distance. You become the witness. This witnessing is the most important thing in spiritual growth. Whatever you can witness, you are not. You are the witness itself.",
                book_title="Awareness: The Key to Living in Balance",
                chapter="The Art of Witnessing",
                chunk_id="sample_awareness_1"
            ),

            # On Mind
            OshoChunk(
                text="The mind is a beautiful servant but a dangerous master. When you are the master, you use the mind as a tool - for planning, for working, for practical purposes. But when the mind becomes the master, you become its slave. You cannot stop thinking even when you want to. The mind goes on and on, chattering endlessly. Meditation is reclaiming your mastery. It is reminding the mind that you are the boss.",
                book_title="The Book of Wisdom",
                chapter="Mind as Servant",
                chunk_id="sample_mind_1"
            ),

            # On Suffering
            OshoChunk(
                text="Pain is inevitable, suffering is optional. Pain is physical, suffering is psychological. When you resist pain, when you fight with it, when you ask 'why me?' - that resistance becomes suffering. But when you accept pain, when you relax into it, it remains only pain. The suffering is created by the mind, not by the body. A Zen master can sit in the cold without suffering because he is not fighting with it.",
                book_title="The Heart Sutra",
                chapter="Pain and Suffering",
                chunk_id="sample_suffering_1"
            ),

            # On Death
            OshoChunk(
                text="Death is not the enemy of life, it is part of life. Just as birth is a beginning, death is an ending. And only with endings can new beginnings happen. If you really accept death, you become fearless. Most of our fears are rooted in the fear of death. Once death is accepted, life opens up in its totality. You can live totally only when you are not afraid of death. Then every moment becomes precious.",
                book_title="The Book of Wisdom",
                chapter="Embracing Death",
                chunk_id="sample_death_1"
            ),

            # On Anger
            OshoChunk(
                text="When anger comes, do not suppress it and do not express it destructively. There is a third way - watch it. Become a witness to your own anger. Sit silently and observe the anger arising in you, the heat in the body, the tension in the muscles. Do not judge it, do not condemn it. Just watch. In that watching, the anger transforms into pure energy. The energy that was anger becomes available for creativity, for love.",
                book_title="The Heart Sutra",
                chapter="Transforming Emotions",
                chunk_id="sample_anger_1"
            ),

            # On Jealousy
            OshoChunk(
                text="Jealousy comes from comparison. You compare yourself with others and feel lacking. But comparison is the root cause of all misery. You are unique. Nobody else in the world is exactly like you. Why compare? The rose does not compare itself with the lotus. Each has its own beauty. When you stop comparing, jealousy disappears. And then you can appreciate others without feeling diminished.",
                book_title="Intimacy: Trusting Oneself and the Other",
                chapter="Beyond Jealousy",
                chunk_id="sample_jealousy_1"
            ),

            # On Relationships
            OshoChunk(
                text="In relationships, people try to change each other. That is the greatest mistake. You fell in love with someone as they were, and then immediately you start trying to change them. Accept the person as they are. If you cannot accept them, do not be with them. But if you choose to be with them, accept them totally. This acceptance is love. This acceptance is respect.",
                book_title="Intimacy: Trusting Oneself and the Other",
                chapter="The Art of Relating",
                chunk_id="sample_relationship_1"
            ),

            # On Zen
            OshoChunk(
                text="Zen is not a philosophy, it is not a religion. Zen is a way of being. It is immediate, direct, without any scriptures, without any middlemen. You do not read about Zen, you become Zen. Every action can be Zen - drinking tea, walking in the garden, washing dishes. When you are totally present in what you are doing, that is Zen. It is not somewhere else, it is right here.",
                book_title="Zen: The Path of Paradox",
                chapter="What is Zen",
                chunk_id="sample_zen_1"
            ),

            # On Scriptures
            OshoChunk(
                text="The scriptures are fingers pointing to the moon. Do not mistake the finger for the moon. The words of Buddha, the words of Krishna, the words of Jesus - they are pointers. They are saying: look within. But people start worshipping the finger. They memorize the scriptures, they debate about the scriptures, and they miss the moon completely. The moon is your own consciousness.",
                book_title="The Mustard Seed",
                chapter="Beyond Words",
                chunk_id="sample_scripture_1"
            ),

            # On the Gita
            OshoChunk(
                text="The Bhagavad Gita is not a book about war. It is a book about the inner war - the war between your lower nature and your higher nature, between unconsciousness and consciousness, between the ego and the soul. Arjuna represents every human being standing at the crossroads, confused, not knowing what to do. And Krishna represents the inner voice, the voice of wisdom that guides you when you are lost.",
                book_title="The Book of Wisdom",
                chapter="The Inner Battle",
                chunk_id="sample_gita_1"
            ),

            # On Tao
            OshoChunk(
                text="Tao means the way - but it is not a fixed path. It is a flowing, like water. Water always finds its way. It does not fight with obstacles, it goes around them. It does not resist, it accepts. And yet, given enough time, water can carve through rock. This is the power of non-resistance, the power of softness. The hard breaks, the soft survives. Be like water.",
                book_title="Tao: The Three Treasures",
                chapter="The Way of Water",
                chunk_id="sample_tao_1"
            ),

            # On Happiness
            OshoChunk(
                text="Happiness is not something you find, it is something you are. You do not have to go anywhere to find it. You just have to stop running. Stop chasing goals, stop postponing life, stop waiting for something to happen. Everything that you need for happiness is already here, right now. It is just that you are not paying attention. When you become present, happiness bubbles up on its own.",
                book_title="Awareness: The Key to Living in Balance",
                chapter="The Secret of Happiness",
                chunk_id="sample_happiness_1"
            ),

            # On Aloneness
            OshoChunk(
                text="There is a difference between loneliness and aloneness. Loneliness is a negative state - you are missing someone. Aloneness is a positive state - you are full in yourself. Loneliness is poverty, aloneness is richness. When you can be alone and feel complete, when you do not need anyone to fill you up, then you are ready for love. Then you can share your fullness. Then love becomes a luxury, not a need.",
                book_title="Love, Freedom, Aloneness",
                chapter="The Beauty of Aloneness",
                chunk_id="sample_aloneness_1"
            ),

            # On Trust
            OshoChunk(
                text="Trust does not mean trusting others - it means trusting yourself. When you trust yourself, you can trust existence. The person who does not trust himself cannot trust anyone. He will always be suspicious, always afraid, always defensive. Self-trust is the foundation of all trust. And self-trust comes from knowing yourself, from being authentic, from being true to your own nature.",
                book_title="Intimacy: Trusting Oneself and the Other",
                chapter="The Root of Trust",
                chunk_id="sample_trust_1"
            ),
        ]

        print(f"[OSHO RAG] Added {len(sample_teachings)} sample teachings")
        return sample_teachings


if __name__ == "__main__":
    # Test the loader
    loader = OshoDataLoader()

    # Try loading books
    chunks = loader.process_all_books()

    if not chunks:
        print("\n[OSHO RAG] No books found. Adding sample teachings...")
        chunks = loader.add_sample_teachings()
        loader.save_chunks(chunks)

    print(f"\n[OSHO RAG] Total chunks available: {len(chunks)}")
