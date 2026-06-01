"""
🎰 Blackjack Twitter Dashboard API
FastAPI backend for the Gambler's Growth Engine
Runs on Port 8052
"""

import sys
import base64
import re
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import uvicorn

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.blackjack_agent import BlackjackAgent
from src.prompts.blackjack.modes import ALL_MODES, CHALLENGE_MODES, ALIGN_MODES, MODE_COLORS

app = FastAPI(
    title="Blackjack Twitter API",
    description="The Gambler's Growth Engine - Dashboard Backend",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lazy-loaded agent
agent = None


def get_agent():
    global agent
    if agent is None:
        agent = BlackjackAgent()
    return agent


# Request Models
class ReplyRequest(BaseModel):
    tweet: str
    mode_filter: Optional[str] = None  # 'challenge', 'align', specific mode, or None


class ImageReplyRequest(BaseModel):
    image_data: str
    caption: str = ""
    mode_filter: Optional[str] = None


class TweetRequest(BaseModel):
    topic: Optional[str] = None
    count: int = 5


class ThreadRequest(BaseModel):
    topic: str
    length: int = 5
    thesis: Optional[str] = None


class ArticleRequest(BaseModel):
    topic: str
    article_type: str = "deep_dive"  # deep_dive, listicle, opinion, howto, contrarian
    length: str = "medium"  # short, medium, long
    thesis: Optional[str] = None


class ArticleSection(BaseModel):
    heading: str
    body: str


class ArticleResponse(BaseModel):
    topic: str
    article_type: str
    length: str
    title: str
    hook: str
    sections: List[ArticleSection]
    closer: str
    full_content: str
    char_count: int
    word_count: int


class TeaserRequest(BaseModel):
    title: str
    hook: str
    key_insight: Optional[str] = ""


class TeaserResponse(BaseModel):
    teaser: str
    char_count: int


# Endpoints
@app.get("/")
async def root():
    """Serve the dashboard"""
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/api/health")
async def health():
    return {"status": "The table is open", "modes": len(ALL_MODES)}


@app.get("/api/modes")
async def get_modes():
    """Get all available modes with their categories"""
    return {
        "all_modes": ALL_MODES,
        "challenge_modes": CHALLENGE_MODES,
        "align_modes": ALIGN_MODES,
        "mode_colors": MODE_COLORS
    }


@app.post("/api/replies")
async def generate_replies(request: ReplyRequest):
    """Generate replies across all modes (or filtered)"""
    try:
        agent = get_agent()

        # First analyze the tweet
        analysis = agent.analyze_tweet(request.tweet)

        # Determine which modes to use
        if request.mode_filter is None:
            modes = ALL_MODES
        elif request.mode_filter == "challenge":
            modes = CHALLENGE_MODES
        elif request.mode_filter == "align":
            modes = ALIGN_MODES
        elif request.mode_filter in ALL_MODES:
            modes = [request.mode_filter]
        else:
            modes = ALL_MODES

        # Generate replies for each mode
        replies = []
        for mode in modes:
            reply_text = agent.generate_reply(request.tweet, mode, analysis)
            replies.append({
                "mode": mode,
                "reply": reply_text,
                "char_count": len(reply_text),
                "color": MODE_COLORS.get(mode, "white")
            })

        return {
            "analysis": {
                "tone": analysis.get("tone", "unknown"),
                "the_bet": analysis.get("the_bet", "unknown"),
                "recommended_mode": analysis.get("recommended_mode", "card_counter"),
                "angle": analysis.get("angle", "unknown"),
                "engagement_potential": analysis.get("engagement_potential", "medium"),
                "is_their_insight_solid": analysis.get("is_their_insight_solid", False)
            },
            "replies": replies,
            "mode_filter": request.mode_filter
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/image-replies")
async def generate_image_replies(request: ImageReplyRequest):
    """Generate replies for an image tweet"""
    try:
        agent = get_agent()

        # Parse image data
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

        # Determine modes
        if request.mode_filter is None:
            modes = ALL_MODES
        elif request.mode_filter == "challenge":
            modes = CHALLENGE_MODES
        elif request.mode_filter == "align":
            modes = ALIGN_MODES
        elif request.mode_filter in ALL_MODES:
            modes = [request.mode_filter]
        else:
            modes = ALL_MODES

        # Analyze image
        image_analysis = agent.analyze_image(image_data, image_media_type)

        # Create analysis from image context
        analysis = {
            "tone": image_analysis.get("tone", "unknown"),
            "the_bet": image_analysis.get("gambling_angle", "their position"),
            "angle": image_analysis.get("hook", "gambling wisdom")
        }

        # Generate replies
        replies = []
        for mode in modes:
            reply_text = agent.generate_image_reply(mode, analysis, image_analysis, request.caption)
            replies.append({
                "mode": mode,
                "reply": reply_text,
                "char_count": len(reply_text),
                "color": MODE_COLORS.get(mode, "white")
            })

        return {
            "image_analysis": {
                "image_type": image_analysis.get("image_type", "unknown"),
                "visible_text": image_analysis.get("visible_text", ""),
                "actual_message": image_analysis.get("actual_message", ""),
                "tone": image_analysis.get("tone", "unknown"),
                "hook": image_analysis.get("hook", "")
            },
            "analysis": analysis,
            "replies": replies,
            "mode_filter": request.mode_filter
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tweets")
async def generate_tweets(request: TweetRequest):
    """Generate original tweets"""
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
    """Generate a Twitter thread"""
    try:
        agent = get_agent()
        thread = agent.generate_thread(request.topic, request.length, request.thesis)

        return {
            "topic": request.topic,
            "tweets": [
                {"text": t, "char_count": len(t), "position": i + 1}
                for i, t in enumerate(thread) if t
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/articles")
async def generate_article(request: ArticleRequest):
    """Generate a Twitter/X Article (long-form content)"""
    try:
        agent = get_agent()
        result = agent.generate_article(
            topic=request.topic,
            article_type=request.article_type,
            length=request.length,
            thesis=request.thesis
        )

        if not result or "error" in result:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to generate article"))

        return {
            "topic": result.get("topic", request.topic),
            "article_type": result.get("article_type", request.article_type),
            "length": result.get("length", request.length),
            "title": result.get("title", ""),
            "hook": result.get("hook", ""),
            "sections": result.get("sections", []),
            "closer": result.get("closer", ""),
            "full_content": result.get("full_content", ""),
            "char_count": result.get("char_count", 0),
            "word_count": result.get("word_count", 0)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/teaser")
async def generate_teaser(request: TeaserRequest):
    """Generate a tweet-length teaser to promote an article"""
    try:
        agent = get_agent()
        teaser = agent.generate_teaser(
            title=request.title,
            hook=request.hook,
            key_insight=request.key_insight or ""
        )

        return {
            "teaser": teaser,
            "char_count": len(teaser)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    print("\n🎰 BLACKJACK TWITTER DASHBOARD")
    print("━" * 40)
    print("Starting on http://localhost:8052")
    print("The house edge is ignorance. Your edge is wisdom.")
    print("━" * 40)
    uvicorn.run(app, host="0.0.0.0", port=8052)
