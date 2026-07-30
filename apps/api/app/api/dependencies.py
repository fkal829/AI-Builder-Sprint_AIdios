from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.adapters.supabase import SupabaseAdapter
from app.core.config import get_settings
from app.core.exceptions import UnauthorizedAccess
from app.services.contracts import ContractService
from app.services.documents import DocumentUploadService
from app.services.idempotency import IdempotencyService
from app.services.public_tokens import PublicTokenService

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def _get_supabase_adapter() -> SupabaseAdapter:
    settings = get_settings()
    return SupabaseAdapter(
        mode=settings.supabase_mode,
        url=settings.supabase_url,
        service_role_key=settings.supabase_service_role_key,
        bucket=settings.supabase_storage_bucket,
        demo_owner_id=settings.demo_owner_id,
        demo_contract_id=settings.demo_contract_id,
        demo_bearer_token=settings.demo_bearer_token,
    )


async def get_supabase_adapter() -> SupabaseAdapter:
    return _get_supabase_adapter()


async def get_document_upload_service(
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
) -> DocumentUploadService:
    settings = get_settings()
    return DocumentUploadService(
        contracts=supabase,
        documents=supabase,
        storage=supabase,
        max_size_bytes=settings.document_max_size_bytes,
        max_pdf_pages=settings.document_max_pdf_pages,
    )


async def get_contract_service(
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
) -> ContractService:
    return ContractService(supabase)


async def get_public_token_service(
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
) -> PublicTokenService:
    return PublicTokenService(
        supabase,
        signing_secret=get_settings().public_token_secret,
    )


async def get_idempotency_service(
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
) -> IdempotencyService:
    return IdempotencyService(supabase)


async def get_current_owner_id(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
) -> UUID:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedAccess()
    owner_id = await supabase.authenticate_owner(credentials.credentials)
    if owner_id is None:
        raise UnauthorizedAccess()
    return owner_id
