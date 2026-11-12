"""API endpoints for managing live streamers and real-time auto-clipping."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_config
from ...database import get_db
from ...services.live_stream_service import LiveStreamService
from ...auth_headers import get_authenticated_user_id

router = APIRouter(prefix="/live-streamers", tags=["live-streamers"])
logger = logging.getLogger(__name__)


class AddStreamerRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    platform: str = Field(..., pattern="^(youtube|twitch|kick)$")
    identifier: str = Field(..., min_length=1, max_length=500, description="Channel handle, URL, or username")
    buffer_minutes: int = Field(default=10, ge=3, le=30)
    min_virality_score: int = Field(default=75, ge=50, le=95)


class ToggleStreamerRequest(BaseModel):
    is_active: bool


@router.get("/")
async def list_streamers(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List all tracked live streamers for the authenticated user."""
    user_id = get_authenticated_user_id(request, get_config())
    return await LiveStreamService.list_streamers(db, user_id)


@router.post("/")
async def add_streamer(
    payload: AddStreamerRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Register a new live streamer to watch."""
    user_id = get_authenticated_user_id(request, get_config())
    try:
        return await LiveStreamService.add_streamer(
            db=db,
            user_id=user_id,
            name=payload.name,
            platform=payload.platform,
            identifier=payload.identifier,
            buffer_minutes=payload.buffer_minutes,
            min_virality_score=payload.min_virality_score,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to add streamer: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to add streamer: {e}")


@router.post("/{streamer_id}/toggle")
async def toggle_streamer(
    streamer_id: str,
    payload: ToggleStreamerRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Pause or resume monitoring a streamer."""
    user_id = get_authenticated_user_id(request, get_config())
    success = await LiveStreamService.toggle_streamer(db, user_id, streamer_id, payload.is_active)
    if not success:
        raise HTTPException(status_code=404, detail="Streamer not found")
    return {"status": "ok", "is_active": payload.is_active}


@router.delete("/{streamer_id}")
async def delete_streamer(
    streamer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Remove a streamer from the watch list."""
    user_id = get_authenticated_user_id(request, get_config())
    success = await LiveStreamService.delete_streamer(db, user_id, streamer_id)
    if not success:
        raise HTTPException(status_code=404, detail="Streamer not found")
    return {"status": "ok", "deleted": True}


@router.get("/{streamer_id}/clips")
async def get_streamer_clips(
    streamer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Return all instant clips generated for a streamer."""
    get_authenticated_user_id(request, get_config())
    return await LiveStreamService.get_streamer_clips(db, streamer_id)
