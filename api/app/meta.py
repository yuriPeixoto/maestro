from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/meta", tags=["meta"])


class MetaOut(BaseModel):
    client_name: str


@router.get("", response_model=MetaOut)
async def get_meta() -> MetaOut:
    """Installation details the interface needs. An empty client name is hidden."""
    return MetaOut(client_name=settings.client_name)
