# Compliance Agent

🌙 TradeHive's Ad Compliance Analyzer for Facebook Advertising Guidelines

## What It Does
- Analyzes TikTok ads for Facebook advertising compliance
- Extracts frames from video ads for visual analysis
- Transcribes audio using Whisper for text analysis
- Checks against Facebook's advertising guidelines
- Provides compliance ratings and recommendations

## Usage
```bash
python src/agents/compliance_agent.py
```

## Key Features
- **Frame Extraction**: Pulls key frames from video ads
- **Audio Transcription**: Converts speech to text for analysis
- **AI Analysis**: Uses GPT-4o-mini to check compliance
- **Detailed Reports**: Generates compliance scores and recommendations

## Compliance Checks
- Personal attributes (no assumptions about viewers)
- Sensational content (shocking/violent imagery)
- Adult content or nudity
- Misleading claims or false information
- Health claims without disclaimers
- Before/after images compliance
- Targeting sensitive categories
- Prohibited products/services
- Text-to-image ratio issues

## Configuration
```python
MODEL_CONFIG = {
    "type": "openai",
    "name": "gpt-4o-mini",
    "reasoning_effort": "high"
}

# Video source directory
VIDEOS_DIR = Path("/Users/md/Dropbox/dev/github/search-arbitrage/bots/compliance/tiktok_ads")
```

## Output Structure
```
src/data/compliance/
├── analysis/
│   ├── frames/        # Extracted video frames
│   ├── transcripts/   # Audio transcriptions
│   └── reports/       # Compliance analysis reports
└── fb_guidelines.txt  # Facebook guidelines reference
```

## Report Format
Each analysis includes:
- **Compliance Status**: compliant/non-compliant
- **Overall Assessment**: Brief summary
- **Compliance Score**: 0-100% rating
- **Specific Issues**: Detailed violations found
- **Recommendations**: How to fix compliance issues

## Example Output
```json
{
  "compliance_status": "non-compliant",
  "overall_assessment": "Ad contains personal attribute assumptions",
  "compliance_score": 65,
  "issues": [
    "Assumes viewer characteristics",
    "Text-to-image ratio too high"
  ],
  "recommendations": [
    "Remove 'You must be...' language",
    "Reduce text overlay on images"
  ],
  "tradehive_message": "TradeHive's magic found some issues to fix! 🌙"
}
```

## Use Cases
- Pre-screen TikTok ads before Facebook submission
- Bulk analyze ad campaigns for compliance
- Identify common compliance issues in ad creative
- Generate compliance reports for clients

## Notes
- Designed for search arbitrage ad campaigns
- Works with TikTok ads being repurposed for Facebook
- Helps avoid ad rejections and account issues
- Part of TradeHive's advertising automation suite