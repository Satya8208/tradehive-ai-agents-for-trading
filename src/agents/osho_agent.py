"""
🌙 TradeHive's Osho Hindi Discourse Agent
Built with love by TradeHive 🚀

This agent processes Osho's Hindi discourses (audio or text),
translates them literally to preserve the fire and intensity,
and generates raw tweet content in Osho's pure voice.
"""

import os
import sys
import json
import time
import shutil
import base64
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv
from openai import OpenAI
import openai

# Fix Unicode encoding on Windows
if sys.platform == "win32":
    import codecs

    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer)
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer)


# Simple colored print that works on all platforms
def cprint(text, color=None, attrs=None, **kwargs):
    """Cross-platform colored print"""
    try:
        from termcolor import cprint as tcprint

        tcprint(text, color, attrs, **kwargs)
    except:
        print(text, **kwargs)


# Import ModelFactory for DeepSeek access
try:
    from src.models.model_factory import model_factory
except ImportError:
    # Fallback if running standalone
    import sys

    sys.path.append(str(Path(__file__).parent.parent.parent))
    from src.models.model_factory import model_factory

# Configuration
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "src" / "data" / "osho_agent"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
PROCESSED_DIR = DATA_DIR / "processed"

# Translation settings
TRANSLATION_MODEL = "deepseek"  # Use DeepSeek for literal translation
TRANSLATION_MODEL_NAME = "deepseek-v4-flash"  # DeepSeek V4 Flash for translation
TWEET_MODEL = "deepseek"  # Use DeepSeek for tweet extraction
TWEET_MODEL_NAME = "deepseek-v4-flash"

# Audio settings - Using OpenRouter with Gemini for transcription
TRANSCRIPTION_MODEL = "google/gemini-2.5-flash"  # Via OpenRouter

# Text processing
MAX_CHUNK_SIZE = 8000  # Characters per chunk for processing
MIN_TWEET_LENGTH = 50  # Minimum characters for a valid tweet
MAX_TWEET_LENGTH = 280  # Twitter character limit

# File extensions
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}
TEXT_EXTENSIONS = {".txt", ".md"}

# Prompts
TRANSLATION_PROMPT = """You are translating Osho's early Hindi discourses to English.

CRITICAL INSTRUCTIONS:
1. Translate LITERALLY - word for word where possible
2. PRESERVE the Hindi sentence structure when it adds impact
3. DO NOT soften the language - keep the fire, the intensity, the confrontation
4. DO NOT add explanations or make it "easier to understand"
5. Keep SHORT, POWERFUL words - no academic or corporate language
6. Maintain the URGENCY and DIRECTNESS that made people uncomfortable
7. PRESERVE paradoxes and provocative statements exactly as they are

The goal: Someone reading this should feel challenged, like comfortable lies are being exposed.

Translate this Hindi text to English, preserving the literal meaning and intensity:

{hindi_text}

Provide ONLY the English translation, nothing else."""

TWEET_EXTRACTION_PROMPT = """Extract tweet-worthy content from this Osho discourse translation.

CRITICAL RULES:
1. Extract ALL statements that challenge beliefs or expose comfortable lies
2. NO LIMIT on number of tweets - extract every fire-worthy statement
3. Create TWO types of output:
   
   STANDALONE TWEETS (≤280 characters):
   - Must be complete, punchy wisdom bombs
   - Start with the impact (no setup)
   - Use simple words
   - Must make reader pause and question
   
   THREAD MATERIAL (longer passages):
   - Extended passages that work as multi-tweet threads
   - Natural breaking points for threading
   - Progressive build-up of insight

4. NO attribution (no "Osho says")
5. NO hashtags
6. NO emojis
7. NO softening - keep the confrontational energy
8. Pure Osho voice - raw, direct, uncomfortable truth

Format your response exactly like this:

===STANDALONE TWEETS===
[tweet 1]

[tweet 2]

[tweet 3]
... (extract ALL worthy tweets, no limit)

===THREAD MATERIAL===
[thread passage 1]

[thread passage 2]

[thread passage 3]
... (extract ALL thread-worthy passages)

Here is the translated discourse:

{translated_text}

Extract every piece of fire. Leave nothing valuable behind."""


class OshoAgent:
    """TradeHive's Osho Hindi Discourse Processor 🌙"""

    def __init__(self):
        """Initialize the Osho Agent"""
        cprint("🌙 Initializing Osho Hindi Discourse Agent...", "cyan")

        # Load environment variables
        load_dotenv()

        # Setup OpenRouter client for audio transcription (uses Gemini)
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_key:
            raise ValueError("🚨 OPENROUTER_API_KEY not found in environment variables!")
        self.openrouter_client = OpenAI(
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1"
        )
        cprint(f"✅ OpenRouter configured for transcription: {TRANSCRIPTION_MODEL}", "green")

        # Setup DeepSeek client for translation and tweet extraction
        deepseek_key = os.getenv("DEEPSEEK_KEY")
        if not deepseek_key:
            raise ValueError("🚨 DEEPSEEK_KEY not found in environment variables!")
        self.deepseek_client = openai.OpenAI(
            api_key=deepseek_key, base_url="https://api.deepseek.com"
        )

        # Create directory structure
        self._setup_directories()

        # Load or create processing log
        self.processed_log = self._load_processed_log()

        cprint("✅ Osho Agent initialized successfully!", "green")
        cprint(f"📁 Input directory: {INPUT_DIR}", "blue")
        cprint(f"📁 Output directory: {OUTPUT_DIR}", "blue")
        cprint("🎙️  Ready to process Hindi discourses...", "cyan")

    def _setup_directories(self):
        """Create necessary directory structure"""
        for directory in [DATA_DIR, INPUT_DIR, OUTPUT_DIR, PROCESSED_DIR]:
            directory.mkdir(parents=True, exist_ok=True)
            cprint(f"📂 Ensured directory exists: {directory}", "blue")

    def _load_processed_log(self) -> Dict:
        """Load or create processing log"""
        log_file = DATA_DIR / "processed_log.json"
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"processed_files": []}

    def _save_processed_log(self):
        """Save processing log"""
        log_file = DATA_DIR / "processed_log.json"
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(self.processed_log, f, indent=2, ensure_ascii=False)

    def _is_already_processed(self, filename: str) -> bool:
        """Check if file has already been processed"""
        return filename in self.processed_log.get("processed_files", [])

    def _mark_as_processed(self, filename: str):
        """Mark file as processed"""
        if filename not in self.processed_log["processed_files"]:
            self.processed_log["processed_files"].append(filename)
            self._save_processed_log()

    def _get_pending_files(self) -> List[Path]:
        """Get list of pending files in input directory"""
        pending = []
        if INPUT_DIR.exists():
            for file_path in INPUT_DIR.iterdir():
                if file_path.is_file():
                    ext = file_path.suffix.lower()
                    if ext in AUDIO_EXTENSIONS or ext in TEXT_EXTENSIONS:
                        if not self._is_already_processed(file_path.name):
                            pending.append(file_path)
        return pending

    def transcribe_audio(self, audio_path: Path) -> str:
        """Transcribe Hindi audio using local Whisper (free, no API needed)"""
        cprint(f"🎙️  Transcribing audio with local Whisper: {audio_path.name}", "yellow")

        try:
            import whisper

            # Load Whisper model (downloads on first use)
            cprint("   🔄 Loading Whisper model...", "blue")
            model = whisper.load_model("base")  # Options: tiny, base, small, medium, large

            # Transcribe
            cprint("   🔄 Transcribing Hindi audio...", "blue")
            result = model.transcribe(
                str(audio_path),
                language="hi",  # Hindi
                fp16=False  # For CPU compatibility
            )

            hindi_text = result["text"].strip()
            cprint(f"✅ Transcription complete: {len(hindi_text)} characters", "green")

            return hindi_text

        except ImportError:
            cprint("❌ Whisper not installed. Installing now...", "yellow")
            import subprocess
            subprocess.run(["pip", "install", "openai-whisper"], check=True)
            # Retry after install
            return self.transcribe_audio(audio_path)

        except Exception as e:
            cprint(f"❌ Error transcribing audio: {str(e)}", "red")
            raise

    def read_text_file(self, text_path: Path) -> str:
        """Read Hindi text from file"""
        cprint(f"📖 Reading text file: {text_path.name}", "yellow")

        try:
            with open(text_path, "r", encoding="utf-8") as f:
                text = f.read()
            cprint(f"✅ Read complete: {len(text)} characters", "green")
            return text

        except Exception as e:
            cprint(f"❌ Error reading text file: {str(e)}", "red")
            raise

    def translate_hindi_to_english(self, hindi_text: str) -> str:
        """Translate Hindi text to English using DeepSeek (literal translation)"""
        cprint("🔄 Translating Hindi to English (literal)...", "yellow")

        # Split into chunks if text is too long
        chunks = [
            hindi_text[i : i + MAX_CHUNK_SIZE]
            for i in range(0, len(hindi_text), MAX_CHUNK_SIZE)
        ]

        translated_chunks = []

        for i, chunk in enumerate(chunks, 1):
            cprint(f"  Processing chunk {i}/{len(chunks)}...", "blue")

            prompt = TRANSLATION_PROMPT.format(hindi_text=chunk)

            try:
                response = self.deepseek_client.chat.completions.create(
                    model=TRANSLATION_MODEL_NAME,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a literal translator. Preserve the fire and intensity.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=4000,
                    temperature=0.3,  # Lower temperature for more literal translation
                )

                translated_chunk = response.choices[0].message.content
                if translated_chunk:
                    translated_chunk = translated_chunk.strip()
                translated_chunks.append(translated_chunk)

                # Small delay to avoid rate limits
                if i < len(chunks):
                    time.sleep(0.5)

            except Exception as e:
                cprint(f"❌ Error translating chunk {i}: {str(e)}", "red")
                raise

        full_translation = "\n\n".join(translated_chunks)
        cprint(f"✅ Translation complete: {len(full_translation)} characters", "green")
        return full_translation

    def extract_tweets(self, translated_text: str) -> Tuple[List[str], List[str]]:
        """Extract standalone tweets and thread material from translated text"""
        cprint("🐦 Extracting tweet content...", "yellow")

        # Split into chunks for processing
        chunks = [
            translated_text[i : i + MAX_CHUNK_SIZE]
            for i in range(0, len(translated_text), MAX_CHUNK_SIZE)
        ]

        all_standalone = []
        all_threads = []

        for i, chunk in enumerate(chunks, 1):
            cprint(f"  Extracting from chunk {i}/{len(chunks)}...", "blue")

            prompt = TWEET_EXTRACTION_PROMPT.format(translated_text=chunk)

            try:
                response = self.deepseek_client.chat.completions.create(
                    model=TWEET_MODEL_NAME,
                    messages=[
                        {
                            "role": "system",
                            "content": "You extract fire content. Be thorough.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=4000,
                    temperature=0.7,  # Higher temperature for creative extraction
                )

                content = response.choices[0].message.content
                standalone: list[str] = []
                threads: list[str] = []
                if content:
                    content = content.strip()

                    # Parse the response
                    standalone, threads = self._parse_extraction_response(content)
                    all_standalone.extend(standalone)
                    all_threads.extend(threads)

                cprint(
                    f"    Found {len(standalone)} standalone tweets, {len(threads)} thread passages",
                    "green",
                )

                # Small delay to avoid rate limits
                if i < len(chunks):
                    time.sleep(0.5)

            except Exception as e:
                cprint(f"❌ Error extracting from chunk {i}: {str(e)}", "red")
                raise

        cprint(
            f"✅ Extraction complete: {len(all_standalone)} standalone tweets, {len(all_threads)} thread passages",
            "green",
        )
        return all_standalone, all_threads

    def _parse_extraction_response(self, content: str) -> Tuple[List[str], List[str]]:
        """Parse the extraction response into standalone tweets and thread material"""
        standalone = []
        threads = []

        # Split by sections
        sections = content.split("===")

        current_section = None
        for section in sections:
            section = section.strip()
            if "STANDALONE TWEETS" in section:
                current_section = "standalone"
                # Get content after the header
                lines = section.split("\n")
                content_start = False
                for line in lines:
                    if content_start and line.strip():
                        if len(line.strip()) >= MIN_TWEET_LENGTH:
                            standalone.append(line.strip())
                    if "STANDALONE TWEETS" in line:
                        content_start = True

            elif "THREAD MATERIAL" in section:
                current_section = "threads"
                # Get content after the header
                lines = section.split("\n")
                content_start = False
                current_thread = []
                for line in lines:
                    if content_start:
                        if line.strip():
                            current_thread.append(line.strip())
                        elif current_thread:
                            # Empty line means end of thread passage
                            thread_text = " ".join(current_thread)
                            if len(thread_text) >= MIN_TWEET_LENGTH:
                                threads.append(thread_text)
                            current_thread = []
                    if "THREAD MATERIAL" in line:
                        content_start = True

                # Don't forget the last thread
                if current_thread:
                    thread_text = " ".join(current_thread)
                    if len(thread_text) >= MIN_TWEET_LENGTH:
                        threads.append(thread_text)

        # Alternative parsing if section headers not found
        if not standalone and not threads:
            # Try to split by blank lines and categorize by length
            paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
            for para in paragraphs:
                if len(para) <= MAX_TWEET_LENGTH and len(para) >= MIN_TWEET_LENGTH:
                    standalone.append(para)
                elif len(para) > MAX_TWEET_LENGTH:
                    threads.append(para)

        return standalone, threads

    def save_output(
        self,
        filename: str,
        standalone_tweets: List[str],
        thread_material: List[str],
        hindi_text: str = "",
        translated_text: str = "",
    ):
        """Save extracted content to output files"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{filename}_{timestamp}"

        # Save standalone tweets
        standalone_file = OUTPUT_DIR / f"{base_name}_standalone.txt"
        with open(standalone_file, "w", encoding="utf-8") as f:
            f.write(f"# Standalone Tweets from {filename}\n")
            f.write(f"# Generated: {datetime.now().isoformat()}\n")
            f.write("# Format: One tweet per line (copy-paste ready)\n")
            f.write("=" * 80 + "\n\n")
            for i, tweet in enumerate(standalone_tweets, 1):
                f.write(f"{tweet}\n\n")

        # Save thread material
        threads_file = OUTPUT_DIR / f"{base_name}_threads.txt"
        with open(threads_file, "w", encoding="utf-8") as f:
            f.write(f"# Thread Material from {filename}\n")
            f.write(f"# Generated: {datetime.now().isoformat()}\n")
            f.write(
                "# Format: Each section is a potential thread (break into tweets manually)\n"
            )
            f.write("=" * 80 + "\n\n")
            for i, thread in enumerate(thread_material, 1):
                f.write(f"## Thread {i}\n\n")
                f.write(f"{thread}\n\n")
                f.write("-" * 80 + "\n\n")

        # Save full translation for reference
        translation_file = None
        if translated_text:
            translation_file = OUTPUT_DIR / f"{base_name}_full_translation.txt"
            with open(translation_file, "w", encoding="utf-8") as f:
                f.write(f"# Full Translation of {filename}\n")
                f.write(f"# Generated: {datetime.now().isoformat()}\n")
                f.write("=" * 80 + "\n\n")
                f.write(translated_text)

        cprint(f"💾 Output saved:", "green")
        cprint(f"   📄 Standalone tweets: {standalone_file}", "blue")
        cprint(f"   📄 Thread material: {threads_file}", "blue")
        if translation_file:
            cprint(f"   📄 Full translation: {translation_file}", "blue")

    def process_file(self, file_path: Path) -> bool:
        """Process a single file (audio or text)"""
        cprint(f"\n{'=' * 80}", "cyan")
        cprint(f"🚀 Processing: {file_path.name}", "cyan", attrs=["bold"])
        cprint(f"{'=' * 80}\n", "cyan")

        try:
            # Step 1: Get Hindi text (transcribe if audio, read if text)
            ext = file_path.suffix.lower()
            if ext in AUDIO_EXTENSIONS:
                hindi_text = self.transcribe_audio(file_path)
            elif ext in TEXT_EXTENSIONS:
                hindi_text = self.read_text_file(file_path)
            else:
                cprint(f"⚠️  Unsupported file type: {ext}", "yellow")
                return False

            if not hindi_text or len(hindi_text.strip()) < 100:
                cprint("⚠️  Text too short or empty, skipping...", "yellow")
                return False

            # Step 2: Translate to English
            translated_text = self.translate_hindi_to_english(hindi_text)

            if not translated_text or len(translated_text.strip()) < 100:
                cprint("⚠️  Translation too short or empty, skipping...", "yellow")
                return False

            # Step 3: Extract tweets
            standalone_tweets, thread_material = self.extract_tweets(translated_text)

            # Step 4: Save output
            self.save_output(
                file_path.stem,
                standalone_tweets,
                thread_material,
                hindi_text,
                translated_text,
            )

            # Step 5: Move to processed folder
            processed_path = PROCESSED_DIR / file_path.name
            shutil.move(str(file_path), str(processed_path))
            cprint(f"📦 Moved to processed: {processed_path.name}", "blue")

            # Step 6: Mark as processed
            self._mark_as_processed(file_path.name)

            # Summary
            cprint(f"\n✅ Processing complete!", "green", attrs=["bold"])
            cprint(f"   📊 Standalone tweets: {len(standalone_tweets)}", "blue")
            cprint(f"   📊 Thread passages: {len(thread_material)}", "blue")

            return True

        except Exception as e:
            cprint(f"❌ Error processing {file_path.name}: {str(e)}", "red")
            return False

    def run(self, continuous: bool = True, interval: int = 30):
        """Run the agent (continuous mode or one-time)"""
        cprint(f"\n🌙 Osho Agent started!", "cyan", attrs=["bold"])
        cprint(f"   Mode: {'Continuous' if continuous else 'One-time'}", "blue")
        if continuous:
            cprint(f"   Check interval: {interval} seconds", "blue")
        cprint(f"   Drop files in: {INPUT_DIR}\n", "yellow")

        try:
            while True:
                # Check for pending files
                pending_files = self._get_pending_files()

                if pending_files:
                    cprint(f"📥 Found {len(pending_files)} pending file(s)", "green")

                    for file_path in pending_files:
                        success = self.process_file(file_path)
                        if not success:
                            cprint(
                                f"⚠️  Failed to process {file_path.name}, will retry later...",
                                "yellow",
                            )

                        # Small delay between files
                        time.sleep(2)
                else:
                    if not continuous:
                        cprint("✅ No pending files. Exiting...", "green")
                        break
                    cprint(
                        f"⏳ No pending files. Checking again in {interval}s...", "blue"
                    )

                if continuous:
                    time.sleep(interval)
                else:
                    break

        except KeyboardInterrupt:
            cprint("\n👋 Osho Agent stopped by user", "yellow")
        except Exception as e:
            cprint(f"\n❌ Fatal error: {str(e)}", "red")
            raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Osho Hindi Discourse Agent")
    parser.add_argument(
        "--once", action="store_true", help="Run once and exit (no continuous mode)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Check interval in seconds (default: 30)",
    )
    parser.add_argument("--file", type=str, help="Process specific file and exit")

    args = parser.parse_args()

    agent = OshoAgent()

    if args.file:
        # Process specific file
        file_path = Path(args.file)
        if file_path.exists():
            agent.process_file(file_path)
        else:
            cprint(f"❌ File not found: {args.file}", "red")
    else:
        # Run in continuous or one-time mode
        agent.run(continuous=not args.once, interval=args.interval)
