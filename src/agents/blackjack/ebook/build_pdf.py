#!/usr/bin/env python3
"""
Blackjack God Ebook PDF Builder
Generates a professional, industry-standard PDF from markdown chapters.

Usage:
    python build_pdf.py              # Build PDF
    python build_pdf.py --html       # Also output HTML for preview
"""

import os
import re
import sys
from pathlib import Path
from datetime import datetime

import markdown
from weasyprint import HTML, CSS

# Configuration
BOOK_TITLE = "BLACKJACK GOD"
BOOK_SUBTITLE = "Beat the House with Math, Not Luck"
YEAR = datetime.now().year

# Paths
SCRIPT_DIR = Path(__file__).parent
CHAPTERS_DIR = SCRIPT_DIR / "chapters"
STYLES_FILE = SCRIPT_DIR / "styles.css"
OUTPUT_DIR = SCRIPT_DIR / "output"

# Chapter order
CHAPTER_ORDER = [
    "00_FRONT_MATTER.md",
    "01_WHY_MOST_LOSE.md",
    "02_BASIC_STRATEGY.md",
    "03_HILO_COUNTING.md",
    "04_TRUE_COUNT.md",
    "05_BETTING_BANKROLL.md",
    "06_CASINO_COUNTERMEASURES.md",
    "07_PRACTICE_PATH.md",
    "08_APPENDIX.md",
]

# Chapter display names for ToC
CHAPTER_NAMES = {
    "00_FRONT_MATTER.md": ("", "Introduction"),
    "01_WHY_MOST_LOSE.md": ("1", "Why Most Blackjack Players Lose"),
    "02_BASIC_STRATEGY.md": ("2", "Basic Strategy — The Foundation"),
    "03_HILO_COUNTING.md": ("3", "Hi-Lo Card Counting"),
    "04_TRUE_COUNT.md": ("4", "True Count Mastery"),
    "05_BETTING_BANKROLL.md": ("5", "Betting Strategy & Bankroll"),
    "06_CASINO_COUNTERMEASURES.md": ("6", "Casino Countermeasures"),
    "07_PRACTICE_PATH.md": ("7", "The Practice Path"),
    "08_APPENDIX.md": ("", "Appendix"),
}


def create_cover_page():
    """Generate the gorgeous dark cover page with Ace of Spades."""
    # Beautiful Ace of Spades SVG
    ace_of_spades = """
    <svg viewBox="0 0 200 280" style="width: 180px; height: 252px; filter: drop-shadow(0 0 40px rgba(212, 168, 83, 0.3));">
        <!-- Card Background -->
        <rect x="0" y="0" width="200" height="280" rx="12" fill="#fefefe" stroke="#d4a853" stroke-width="2"/>

        <!-- Inner Border -->
        <rect x="8" y="8" width="184" height="264" rx="8" fill="none" stroke="#d4a853" stroke-width="1" opacity="0.5"/>

        <!-- Top Left Corner -->
        <text x="18" y="38" font-family="Cinzel, serif" font-size="28" font-weight="700" fill="#1a1a1a">A</text>
        <text x="22" y="60" font-family="serif" font-size="22" fill="#1a1a1a">♠</text>

        <!-- Bottom Right Corner (inverted) -->
        <text x="182" y="252" font-family="Cinzel, serif" font-size="28" font-weight="700" fill="#1a1a1a" text-anchor="end" transform="rotate(180, 173, 244)">A</text>
        <text x="178" y="230" font-family="serif" font-size="22" fill="#1a1a1a" text-anchor="end" transform="rotate(180, 169, 222)">♠</text>

        <!-- Center Spade - Large & Ornate -->
        <g transform="translate(100, 130)">
            <!-- Main Spade Shape -->
            <path d="M0,-55
                     C-8,-55 -45,-25 -45,10
                     C-45,35 -25,50 0,35
                     C25,50 45,35 45,10
                     C45,-25 8,-55 0,-55 Z"
                  fill="#1a1a1a"/>
            <!-- Spade Stem -->
            <path d="M-12,30 L-12,55 C-12,62 -8,65 0,65 C8,65 12,62 12,55 L12,30
                     C5,40 -5,40 -12,30 Z"
                  fill="#1a1a1a"/>
            <!-- Gold Accent Lines -->
            <path d="M0,-45 C-5,-45 -35,-20 -35,8 C-35,25 -20,38 0,28"
                  fill="none" stroke="#d4a853" stroke-width="1.5" opacity="0.6"/>
        </g>

        <!-- Decorative Gold Flourishes -->
        <path d="M40,140 Q60,135 80,140" fill="none" stroke="#d4a853" stroke-width="1" opacity="0.4"/>
        <path d="M120,140 Q140,135 160,140" fill="none" stroke="#d4a853" stroke-width="1" opacity="0.4"/>

        <!-- Subtle Pattern -->
        <circle cx="100" cy="220" r="15" fill="none" stroke="#d4a853" stroke-width="0.5" opacity="0.3"/>
        <circle cx="100" cy="60" r="15" fill="none" stroke="#d4a853" stroke-width="0.5" opacity="0.3"/>
    </svg>
    """

    return f"""
    <div class="cover-page">
        <div style="position: relative; z-index: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%;">
            <!-- Ace of Spades Card -->
            <div style="margin-bottom: 35px;">
                {ace_of_spades}
            </div>

            <!-- Title -->
            <h1 class="cover-title">{BOOK_TITLE}</h1>
            <p class="cover-subtitle">{BOOK_SUBTITLE}</p>
            <p class="cover-tagline">Master Card Counting. Perfect Your Strategy. Beat the House.</p>
        </div>

        <!-- Bottom Decoration -->
        <div class="cover-decoration">♠ ♥ ♣ ♦</div>
    </div>
    """


def create_title_page():
    """Generate the inner title page."""
    return f"""
    <div class="title-page">
        <h1 style="font-size: 26pt; margin-top: 0; border: none; page-break-before: avoid; text-transform: uppercase; letter-spacing: 4px;">{BOOK_TITLE}</h1>
        <p class="subtitle">{BOOK_SUBTITLE}</p>
        <p class="copyright">
            &copy; {YEAR} All Rights Reserved<br><br>
            No part of this publication may be reproduced, distributed, or transmitted<br>
            in any form without prior written permission.<br><br>
            <span style="color: #a68a3f;">blackjackgod.com</span>
        </p>
    </div>
    """


def create_toc():
    """Generate table of contents."""
    toc_items = []

    for filename in CHAPTER_ORDER:
        if filename in CHAPTER_NAMES:
            num, title = CHAPTER_NAMES[filename]
            if num:
                toc_items.append(f'<li><span class="chapter-num">Chapter {num}</span> — {title}</li>')
            else:
                toc_items.append(f'<li><span class="chapter-num"></span>{title}</li>')

    return f"""
    <div class="toc">
        <h2 style="text-align: center; border: none; margin-top: 1in; font-size: 14pt; letter-spacing: 4px; text-transform: uppercase;">Contents</h2>
        <ul style="list-style: none; padding-left: 0; margin-top: 0.8in; max-width: 4in; margin-left: auto; margin-right: auto;">
            {''.join(toc_items)}
        </ul>
    </div>
    """


def process_markdown(content, chapter_index):
    """Process markdown content with enhancements."""
    # Note: Page breaks are handled by CSS h1 { page-break-before: always; }
    # Removed redundant Python-injected page breaks that caused blank pages

    # Color-code strategy chart values
    # Hit = Green, Stand = Blue, Double = Purple, Split = Red
    replacements = [
        (r'\|\s*H\s*\|', '| <span style="color: #2e7d32; font-weight: 600;">H</span> |'),
        (r'\|\s*S\s*\|', '| <span style="color: #1565c0; font-weight: 600;">S</span> |'),
        (r'\|\s*D\s*\|', '| <span style="color: #7b1fa2; font-weight: 600;">D</span> |'),
        (r'\|\s*P\s*\|', '| <span style="color: #c62828; font-weight: 600;">P</span> |'),
        (r'\|\s*Dh\s*\|', '| <span style="color: #7b1fa2; font-weight: 600;">Dh</span> |'),
        (r'\|\s*Ds\s*\|', '| <span style="color: #7b1fa2; font-weight: 600;">Ds</span> |'),
        (r'\|\s*Ph\s*\|', '| <span style="color: #c62828; font-weight: 600;">Ph</span> |'),
        (r'\|\s*Rh\s*\|', '| <span style="color: #e65100; font-weight: 600;">Rh</span> |'),
        (r'\|\s*Rs\s*\|', '| <span style="color: #e65100; font-weight: 600;">Rs</span> |'),
        (r'\|\s*Rp\s*\|', '| <span style="color: #e65100; font-weight: 600;">Rp</span> |'),
    ]

    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content)

    return content


def read_chapters():
    """Read all chapter files in order."""
    chapters = []

    for filename in CHAPTER_ORDER:
        filepath = CHAPTERS_DIR / filename
        if filepath.exists():
            print(f"  📖 {filename}")
            with open(filepath, 'r', encoding='utf-8') as f:
                chapters.append(f.read())
        else:
            print(f"  ⚠️  Missing: {filename}")

    return chapters


def build_html(chapters):
    """Build complete HTML document from chapters."""
    # Process each chapter
    processed_chapters = []
    for i, chapter in enumerate(chapters):
        processed = process_markdown(chapter, i)
        processed_chapters.append(processed)

    # Combine all chapters
    combined_markdown = "\n\n---\n\n".join(processed_chapters)

    # Convert to HTML
    md = markdown.Markdown(
        extensions=[
            'tables',
            'fenced_code',
            'toc',
            'smarty',
            'sane_lists',
        ]
    )
    content_html = md.convert(combined_markdown)

    # Build full HTML document
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{BOOK_TITLE} — {BOOK_SUBTITLE}</title>
    <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600;700&family=Outfit:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
</head>
<body>
    {create_cover_page()}
    {create_title_page()}
    {create_toc()}
    <div class="content">
        {content_html}
    </div>
</body>
</html>
"""
    return html


def build_pdf(html_content, output_path):
    """Generate PDF from HTML content."""
    print(f"\n  🖨️  Rendering PDF...")

    # Read CSS
    css_content = ""
    if STYLES_FILE.exists():
        with open(STYLES_FILE, 'r', encoding='utf-8') as f:
            css_content = f.read()

    # Generate PDF
    html_doc = HTML(string=html_content, base_url=str(SCRIPT_DIR))
    css = CSS(string=css_content)

    html_doc.write_pdf(output_path, stylesheets=[css])

    return output_path


def main():
    print()
    print("  ♠ ♥ ♣ ♦  BLACKJACK GOD  ♦ ♣ ♥ ♠")
    print("  ─────────────────────────────────")
    print("       Professional PDF Builder")
    print()

    # Create output directory
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Read chapters
    print("  [1/3] Loading chapters...")
    chapters = read_chapters()
    print(f"\n      ✓ {len(chapters)} chapters loaded")

    # Build HTML
    print("\n  [2/3] Building document...")
    html_content = build_html(chapters)

    # Save HTML if requested
    if "--html" in sys.argv:
        html_path = OUTPUT_DIR / "blackjack_god.html"
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"      ✓ HTML: {html_path.name}")

    # Generate PDF
    print("\n  [3/3] Generating PDF...")
    timestamp = datetime.now().strftime("%Y%m%d")
    pdf_filename = f"Blackjack_God_{timestamp}.pdf"
    pdf_path = OUTPUT_DIR / pdf_filename

    build_pdf(html_content, str(pdf_path))

    # Calculate file size
    size_mb = pdf_path.stat().st_size / (1024 * 1024)

    # Get page count
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
    except:
        page_count = "?"

    print()
    print("  ═══════════════════════════════════")
    print("  ✓ SUCCESS!")
    print(f"  ─────────────────────────────────")
    print(f"  📄 {pdf_filename}")
    print(f"  📊 {page_count} pages | {size_mb:.2f} MB")
    print(f"  📁 {OUTPUT_DIR}")
    print("  ═══════════════════════════════════")
    print()

    return pdf_path


if __name__ == "__main__":
    main()
