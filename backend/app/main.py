"""FastAPI entry point for the PhantomShip backend."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router as api_router
from app.config import SETTINGS
from app.state import state_engine


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await state_engine.start()
    try:
        yield
    finally:
        await state_engine.stop()


app = FastAPI(
    title="PhantomShip API",
    description=(
        "Maritime cyber-intel API. Streams vessel positions and emits "
        "anomaly threats from a stack of rule-based and ML detectors."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(SETTINGS.cors_origins) + ["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/")
async def root() -> dict:
    return {
        "service": "PhantomShip",
        "version": "1.0.0",
        "mode": state_engine.mode,
        "docs": "/docs",
    }
