"""Local-only private object reader for expiring mock Storage URLs."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.adapters.supabase import SupabaseAdapter
from app.api.dependencies import get_supabase_adapter

router = APIRouter()


@router.get("/{token}", include_in_schema=False)
async def get_mock_signed_object(
    token: str,
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
) -> Response:
    private_object = await supabase.get_mock_signed_object(token=token)
    if private_object is None:
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    return Response(
        content=private_object.content,
        media_type=private_object.content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
