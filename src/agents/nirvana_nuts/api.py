"""
🥜 Nirvana Nuts API
Dedicated backend for the Twitter Growth Engine
Built with love by TradeHive
"""

import sys
import base64
import re
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
import uvicorn

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.nirvana_nuts_agent import NirvanaNutsAgent
from src.prompts.nirvana_nuts.modes import ALL_MODES, CHALLENGE_MODES, ALIGN_MODES

# Osho RAG imports
try:
    from src.agents.nirvana_nuts.osho_rag import OshoRetriever
    OSHO_RAG_AVAILABLE = True
except ImportError:
    OSHO_RAG_AVAILABLE = False
    print("[WARNING] Osho RAG not available - chromadb may not be installed")

app = FastAPI(
    title="🥜 Nirvana Nuts API",
    description="Twitter Growth Engine - Dedicated Backend",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
static_dir = Path(__file__).parent
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Global agent instance
agent = None
osho_retriever = None


def get_agent():
    global agent
    if agent is None:
        agent = NirvanaNutsAgent()
    return agent


def get_osho_retriever():
    global osho_retriever
    if osho_retriever is None and OSHO_RAG_AVAILABLE:
        osho_retriever = OshoRetriever(embedding_provider="default", auto_init=True)
    return osho_retriever


# ===== Pydantic Models =====

class ReplyRequest(BaseModel):
    tweet: str
    mode_filter: Optional[str] = None  # "challenge", "align", or specific mode name


class ImageReplyRequest(BaseModel):
    image_data: str  # Base64 encoded
    caption: str = ""
    mode_filter: Optional[str] = None  # "challenge", "align", or specific mode name


class ReplyOption(BaseModel):
    mode: str
    reply: str
    char_count: int


class AnalysisResult(BaseModel):
    tone: str
    assumptions: str = ""
    angle: str
    recommended_mode: str
    why: str = ""
    engagement_potential: str


class ReplyResponse(BaseModel):
    analysis: AnalysisResult
    replies: List[ReplyOption]


class TweetRequest(BaseModel):
    topic: Optional[str] = None
    count: int = 5


class TweetResponse(BaseModel):
    topic: str
    tweets: List[dict]


class ThreadRequest(BaseModel):
    topic: str
    length: int = 5
    thesis: Optional[str] = None


class ThreadResponse(BaseModel):
    topic: str
    tweets: List[dict]


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


class OshoWisdomRequest(BaseModel):
    question: str
    top_k: int = 5


class OshoPassage(BaseModel):
    text: str
    book_title: str
    chapter: str = ""
    relevance_score: float = 0.0


class OshoWisdomResponse(BaseModel):
    question: str
    answer: str
    passages: List[OshoPassage]
    sources: List[str]


class OshoStatsResponse(BaseModel):
    total_passages: int
    books: List[str]
    rag_available: bool


# ===== API Endpoints =====

@app.get("/")
async def root():
    """Serve the dashboard"""
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        content = html_path.read_text(encoding="utf-8")
        return HTMLResponse(content=content, status_code=200, media_type="text/html; charset=utf-8")
    return {"message": "🥜 Nirvana Nuts Growth Engine API", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy", "agent": "nirvana_nuts"}


@app.post("/api/replies", response_model=ReplyResponse)
async def generate_replies(request: ReplyRequest):
    """Generate reply options for a tweet"""
    try:
        agent = get_agent()

        # Get analysis
        analysis = agent.analyze_tweet(request.tweet)

        # Select modes based on filter (using imported constants)
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
                "assumptions": analysis.get("assumptions", "unknown"),
                "angle": analysis.get("angle", "unknown"),
                "recommended_mode": analysis.get("recommended_mode", "savage"),
                "why": analysis.get("why", ""),
                "engagement_potential": analysis.get("engagement_potential", "medium")
            },
            "replies": replies
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/image-replies")
async def generate_image_replies(request: ImageReplyRequest):
    """Generate reply options for an image tweet"""
    try:
        agent = get_agent()
        print(f"[API] Processing image reply request...")

        # Parse the base64 image data
        image_data = request.image_data
        image_media_type = "image/png"

        if image_data.startswith("data:"):
            match = re.match(r"data:(image/[^;]+);base64,(.+)", image_data)
            if match:
                image_media_type = match.group(1)
                image_data = match.group(2)
            elif ";base64," in image_data:
                image_data = image_data.split(";base64,")[1]

        # Generate replies
        replies, analysis, image_analysis = agent.generate_replies_for_image(
            image_data=image_data,
            caption=request.caption,
            image_media_type=image_media_type,
            mode_filter=request.mode_filter
        )

        return {
            "image_analysis": {
                "image_type": image_analysis.get("image_type", "unknown"),
                "visible_text": image_analysis.get("visible_text", ""),
                "description": image_analysis.get("description", ""),
                "actual_message": image_analysis.get("actual_message", ""),
                "tone": image_analysis.get("tone", "unknown"),
                "hook": image_analysis.get("hook", "")
            },
            "analysis": {
                "tone": analysis.get("tone", "unknown"),
                "assumptions": analysis.get("assumptions", "unknown"),
                "angle": analysis.get("angle", "unknown"),
                "recommended_mode": analysis.get("recommended_mode", "savage"),
                "why": analysis.get("why", ""),
                "engagement_potential": analysis.get("engagement_potential", "medium")
            },
            "replies": [
                {"mode": r["mode"], "reply": r["reply"], "char_count": len(r["reply"])}
                for r in replies
            ]
        }
    except Exception as e:
        print(f"[API] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tweets", response_model=TweetResponse)
async def generate_tweets(request: TweetRequest):
    """Generate original tweet ideas"""
    try:
        agent = get_agent()
        print(f"[API] Generating {request.count} tweets on topic: {request.topic}")

        tweets = agent.generate_tweets(request.topic, request.count)

        if not tweets:
            tweets = []

        topic_used = request.topic or "random topic"

        result = {
            "topic": topic_used,
            "tweets": [{"text": t, "char_count": len(t)} for t in tweets if t]
        }
        print(f"[API] Returning {len(result['tweets'])} tweets")
        return result

    except Exception as e:
        print(f"[API] Error generating tweets: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/thread", response_model=ThreadResponse)
async def generate_thread(request: ThreadRequest):
    """Generate a Twitter thread"""
    try:
        agent = get_agent()
        print(f"[API] Generating {request.length}-tweet thread on: {request.topic}")

        thread = agent.generate_thread(request.topic, request.length, request.thesis)

        if not thread:
            thread = []

        roles = ["HOOK"] + ["BODY"] * (len(thread) - 2) + ["CLOSER"] if len(thread) > 1 else ["HOOK"]

        result = {
            "topic": request.topic,
            "tweets": [
                {"text": t, "char_count": len(t), "role": roles[i] if i < len(roles) else "BODY"}
                for i, t in enumerate(thread) if t
            ]
        }
        print(f"[API] Returning {len(result['tweets'])} thread tweets")
        return result

    except Exception as e:
        print(f"[API] Error generating thread: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/articles", response_model=ArticleResponse)
async def generate_article(request: ArticleRequest):
    """Generate a Twitter/X Article (long-form content)"""
    try:
        agent = get_agent()
        print(f"[API] Generating {request.article_type} article on: {request.topic}")
        print(f"[API] Target length: {request.length}")

        article = agent.generate_article(
            topic=request.topic,
            article_type=request.article_type,
            length=request.length,
            thesis=request.thesis
        )

        if not article or "error" in article:
            raise HTTPException(
                status_code=500,
                detail=article.get("error", "Failed to generate article")
            )

        result = {
            "topic": article.get("topic", request.topic),
            "article_type": article.get("article_type", request.article_type),
            "length": article.get("length", request.length),
            "title": article.get("title", ""),
            "hook": article.get("hook", ""),
            "sections": article.get("sections", []),
            "closer": article.get("closer", ""),
            "full_content": article.get("full_content", ""),
            "char_count": article.get("char_count", 0),
            "word_count": article.get("word_count", 0)
        }

        print(f"[API] Generated article: {result['char_count']} chars, {result['word_count']} words")
        return result

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error generating article: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/teaser", response_model=TeaserResponse)
async def generate_teaser(request: TeaserRequest):
    """Generate a tweet-length teaser to promote an article"""
    try:
        agent = get_agent()
        print(f"[API] Generating teaser for article: {request.title[:50]}...")

        teaser = agent.generate_teaser(
            title=request.title,
            hook=request.hook,
            key_insight=request.key_insight or ""
        )

        result = {
            "teaser": teaser,
            "char_count": len(teaser)
        }

        print(f"[API] Generated teaser: {result['char_count']} chars")
        return result

    except Exception as e:
        print(f"[API] Error generating teaser: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ===== OSHO WISDOM RAG ENDPOINTS =====

@app.post("/api/osho-wisdom", response_model=OshoWisdomResponse)
async def ask_osho_wisdom(request: OshoWisdomRequest):
    """
    Ask Osho a question and get a wisdom response powered by RAG.
    Retrieves relevant passages from Osho's teachings and generates
    an authentic Osho-style response.
    """
    if not OSHO_RAG_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Osho RAG not available. Install chromadb: pip install chromadb"
        )

    try:
        retriever = get_osho_retriever()
        if retriever is None:
            raise HTTPException(
                status_code=503,
                detail="Failed to initialize Osho retriever"
            )

        print(f"[API] Osho wisdom request: {request.question[:50]}...")

        # Get wisdom response using Claude Sonnet 4.6
        result = retriever.ask_osho(
            question=request.question,
            top_k=request.top_k,
            model_provider="claude"
        )

        # Format passages for response
        passages = [
            OshoPassage(
                text=p.get("text", ""),
                book_title=p.get("book_title", ""),
                chapter=p.get("chapter", ""),
                relevance_score=p.get("relevance_score", 0)
            )
            for p in result.passages
        ]

        response = {
            "question": result.question,
            "answer": result.answer,
            "passages": passages,
            "sources": result.sources
        }

        print(f"[API] Osho wisdom generated with {len(passages)} source passages")
        return response

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error in Osho wisdom: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/osho-stats", response_model=OshoStatsResponse)
async def get_osho_stats():
    """Get statistics about the Osho knowledge base"""
    if not OSHO_RAG_AVAILABLE:
        return {
            "total_passages": 0,
            "books": [],
            "rag_available": False
        }

    try:
        retriever = get_osho_retriever()
        if retriever is None:
            return {
                "total_passages": 0,
                "books": [],
                "rag_available": False
            }

        stats = retriever.get_stats()
        return {
            "total_passages": stats["total_passages"],
            "books": stats["books"],
            "rag_available": True
        }
    except Exception as e:
        print(f"[API] Error getting Osho stats: {str(e)}")
        return {
            "total_passages": 0,
            "books": [],
            "rag_available": False
        }


@app.post("/api/osho-refresh")
async def refresh_osho_knowledge():
    """Refresh the Osho knowledge base from raw books"""
    if not OSHO_RAG_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Osho RAG not available"
        )

    try:
        retriever = get_osho_retriever()
        if retriever is None:
            raise HTTPException(
                status_code=503,
                detail="Failed to initialize Osho retriever"
            )

        count = retriever.refresh_from_books()
        return {"status": "success", "passages_loaded": count}

    except Exception as e:
        print(f"[API] Error refreshing Osho knowledge: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  NIRVANA NUTS GROWTH ENGINE")
    print("  Built with love by TradeHive")
    print("=" * 50)
    print("\n  Open http://localhost:8050 in your browser\n")
    print("=" * 50 + "\n")

    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8050,
        reload=True
    )
