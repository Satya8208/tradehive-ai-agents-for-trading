"""
Standalone FastAPI app for the Polymarket weather terminal.

This app is intentionally separate from the main operator dashboard API so the
weather trading control room can run on its own port and lifecycle.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.dashboard.backend.polymarket_weather_api import router as polymarket_weather_router


app = FastAPI(
    title="Polymarket Weather Terminal API",
    description="Standalone API for the paper-only Polymarket weather control room.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3020",
        "http://127.0.0.1:3020",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(polymarket_weather_router)


@app.get("/")
async def root():
    return {
        "name": "Polymarket Weather Terminal API",
        "status": "running",
        "frontend": "http://localhost:3020/",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "polymarket-weather-terminal",
        "live_trading": "hard_blocked",
    }
