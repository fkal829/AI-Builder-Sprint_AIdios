from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.adapters.modusign import ModusignAdapter
from app.adapters.solar import SolarReviewAdapter
from app.adapters.supabase import SupabaseAdapter
from app.adapters.upstage import UpstageAdapter
from app.core.config import get_settings
from app.core.exceptions import UnauthorizedAccess
from app.services.adjustments import AdjustmentService
from app.services.agreement_pdf import AgreementPdfRenderer
from app.services.agreements import AgreementService
from app.services.analysis import AnalysisService
from app.services.contracts import ContractService
from app.services.counterproposal import CounterproposalComparator
from app.services.documents import DocumentAccessService, DocumentUploadService
from app.services.idempotency import IdempotencyService
from app.services.obligations import ObligationService
from app.services.public_tokens import PublicTokenService
from app.services.review_items import ReviewItemService
from app.services.signatures import SignatureService
from app.services.understood_terms import UnderstoodTermService

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
        mock_storage_access_base_url=settings.supabase_mock_storage_access_base_url,
    )


async def get_supabase_adapter() -> SupabaseAdapter:
    return _get_supabase_adapter()


@lru_cache
def _get_upstage_adapter() -> UpstageAdapter:
    settings = get_settings()
    return UpstageAdapter(
        mode=settings.upstage_mode,
        api_key=settings.upstage_api_key,
        base_url=settings.upstage_base_url,
        parse_timeout_seconds=settings.upstage_parse_timeout_seconds,
        extract_timeout_seconds=settings.upstage_extract_timeout_seconds,
        extract_model=settings.upstage_extract_model,
    )


async def get_upstage_adapter() -> UpstageAdapter:
    return _get_upstage_adapter()


@lru_cache
def _get_solar_review_adapter() -> SolarReviewAdapter:
    settings = get_settings()
    return SolarReviewAdapter(
        mode=settings.upstage_mode,
        api_key=settings.upstage_api_key,
        base_url=settings.upstage_base_url,
        timeout_seconds=settings.upstage_solar_timeout_seconds,
        model=settings.upstage_solar_model,
    )


async def get_solar_review_adapter() -> SolarReviewAdapter:
    return _get_solar_review_adapter()


@lru_cache
def _get_modusign_adapter() -> ModusignAdapter:
    settings = get_settings()
    return ModusignAdapter(
        account_email=settings.modusign_account_email,
        api_key=settings.modusign_api_key,
        mode=settings.modusign_mode,
    )


async def get_modusign_adapter() -> ModusignAdapter:
    return _get_modusign_adapter()


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


async def get_document_access_service(
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
) -> DocumentAccessService:
    return DocumentAccessService(
        documents=supabase,
        storage=supabase,
    )


async def get_understood_term_service(
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
) -> UnderstoodTermService:
    return UnderstoodTermService(repository=supabase)


async def get_analysis_service(
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
    upstage: Annotated[UpstageAdapter, Depends(get_upstage_adapter)],
    solar: Annotated[SolarReviewAdapter, Depends(get_solar_review_adapter)],
) -> AnalysisService:
    return AnalysisService(
        adapter=upstage,
        reviewer=solar,
        contracts=supabase,
        documents=supabase,
        understood_terms=supabase,
        analyses=supabase,
        storage=supabase,
    )


async def get_review_item_service(
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
) -> ReviewItemService:
    return ReviewItemService(repository=supabase)


async def get_contract_service(
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
) -> ContractService:
    return ContractService(supabase)


async def get_obligation_service(
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
) -> ObligationService:
    return ObligationService(supabase)


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


async def get_counterproposal_comparator(
    solar: Annotated[SolarReviewAdapter, Depends(get_solar_review_adapter)],
) -> CounterproposalComparator:
    return CounterproposalComparator(solar)


async def get_adjustment_service(
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
    counterproposal_comparator: Annotated[
        CounterproposalComparator,
        Depends(get_counterproposal_comparator),
    ],
) -> AdjustmentService:
    settings = get_settings()
    return AdjustmentService(
        repository=supabase,
        counterproposal_comparator=counterproposal_comparator,
        idempotency=IdempotencyService(supabase),
        public_tokens=PublicTokenService(
            supabase,
            signing_secret=settings.public_token_secret,
        ),
        public_app_base_url=settings.public_app_base_url,
    )


async def get_agreement_service(
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
) -> AgreementService:
    return AgreementService(
        repository=supabase,
        idempotency=IdempotencyService(supabase),
    )


async def get_signature_service(
    supabase: Annotated[SupabaseAdapter, Depends(get_supabase_adapter)],
    modusign: Annotated[ModusignAdapter, Depends(get_modusign_adapter)],
) -> SignatureService:
    return SignatureService(
        repository=supabase,
        agreements=supabase,
        modusign=modusign,
        agreement_pdf=AgreementPdfRenderer(font_path=get_settings().agreement_pdf_font_path),
        embedded_redirect_url=get_settings().modusign_embedded_redirect_url,
    )


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
