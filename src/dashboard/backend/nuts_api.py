"""
⚠️ DEPRECATED - This file is no longer maintained.

Use the main API at: src/agents/nirvana_nuts/api.py

To run the dashboard:
    cd src/agents/nirvana_nuts && python api.py

Or:
    python -m src.agents.nirvana_nuts.api

The main API includes:
- Full mode support (8 modes)
- Mode filtering (challenge/align)
- Static file serving for dashboard
- Better error handling

This file is kept for reference only.
"""

raise DeprecationWarning(
    "This API is deprecated. Use src/agents/nirvana_nuts/api.py instead. "
    "Run: cd src/agents/nirvana_nuts && python api.py"
)

# Original deprecated code below
"""
🥜 Nirvana Nuts API (DEPRECATED)
Dedicated backend for the Twitter Growth Engine
Runs on Port 8050
"""

import sys
import base64
import re
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import uvicorn

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.nirvana_nuts_agent import NirvanaNutsAgent

app = FastAPI(
    title="Nirvana Nuts API",
    description="Dedicated backend for Twitter Agent",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = None

def get_agent():
    global agent
    if agent is None:
        agent = NirvanaNutsAgent()
    return agent

# Models
class ReplyRequest(BaseModel):
    tweet: str

class ImageReplyRequest(BaseModel):
    image_data: str
    caption: str = ""

class TweetRequest(BaseModel):
    topic: Optional[str] = None
    count: int = 5

class ThreadRequest(BaseModel):
    topic: str
    length: int = 5
    thesis: Optional[str] = None

@app.get("/")
async def root():
    return {"status": "Nirvana Nuts is Online 🥜"}

@app.post("/api/replies")
async def generate_replies(request: ReplyRequest):
    try:
        agent = get_agent()
        analysis = agent.analyze_tweet(request.tweet)
        modes = ["savage", "funny", "philosophical", "controversial", "nuclear", "osho", "align_insight", "align_humor"]
        replies = []

        for mode in modes:
            reply_text = agent.generate_reply(request.tweet, mode, analysis)
            replies.append({
                "mode": mode,
                "reply": reply_text,
                "char_count": len(reply_text)
            })

        return {
            "analysis": {
                "tone": analysis.get("tone", "unknown"),
                "recommended_mode": analysis.get("recommended_mode", "savage"),
                "angle": analysis.get("angle", "unknown"),
                "engagement_potential": analysis.get("engagement_potential", "medium")
            },
            "replies": replies
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/image-replies")
async def generate_image_replies(request: ImageReplyRequest):
    try:
        agent = get_agent()
        image_data = request.image_data
        image_media_type = "image/png"

        if image_data.startswith("data:"):
            match = re.match(r"data:(image/[^;]+);base64,(.+)", image_data)
            if match:
                image_media_type = match.group(1)
                image_data = match.group(2)
            else:
                if ";base64," in image_data:
                    image_data = image_data.split(";base64,")[1]

        replies, analysis, image_analysis = agent.generate_replies_for_image(
            image_data=image_data,
            caption=request.caption,
            image_media_type=image_media_type
        )

        return {
            "image_analysis": {
                "image_type": image_analysis.get("image_type", "unknown"),
                "visible_text": image_analysis.get("visible_text", ""),
                "actual_message": image_analysis.get("actual_message", ""),
                "tone": image_analysis.get("tone", "unknown"),
                "hook": image_analysis.get("hook", "")
            },
            "analysis": {
                "tone": analysis.get("tone", "unknown"),
                "recommended_mode": analysis.get("recommended_mode", "savage"),
                "engagement_potential": analysis.get("engagement_potential", "medium")
            },
            "replies": [
                {"mode": r["mode"], "reply": r["reply"], "char_count": len(r["reply"])}
                for r in replies
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tweets")
async def generate_tweets(request: TweetRequest):
    try:
        agent = get_agent()
        tweets = agent.generate_tweets(request.topic, request.count)
        return {
            "topic": request.topic or "random",
            "tweets": [{"text": t, "char_count": len(t)} for t in tweets if t]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/thread")
async def generate_thread(request: ThreadRequest):
    try:
        agent = get_agent()
        thread = agent.generate_thread(request.topic, request.length, request.thesis)
        return {
            "topic": request.topic,
            "tweets": [{"text": t, "char_count": len(t)} for i, t in enumerate(thread) if t]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8050)
