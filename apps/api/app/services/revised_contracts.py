import hashlib
import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.adapters.base import DocumentAnalysisAdapter, ParsedDocument
from app.core.exceptions import InvalidDocument, ResourceNotFound
from app.repositories.documents import DocumentRepository, PrivateStorage
from app.repositories.revised_contracts import RevisedContractRepository
from app.schemas.documents import DocumentType
from app.schemas.revised_contracts import (
    RevisedContractMatchStatus,
    RevisedContractReview,
    RevisedContractReviewConfirmation,
    RevisedContractReviewCreate,
    RevisedContractReviewItem,
    RevisedContractReviewStatus,
)
from app.services.state_machine import InvalidStatusTransition


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"[\s\u00a0]+", "", normalized)


def _normalized_text_with_offsets(value: str) -> tuple[str, tuple[int, ...]]:
    characters: list[str] = []
    original_offsets: list[int] = []
    for original_offset, character in enumerate(value):
        for normalized_character in unicodedata.normalize("NFKC", character).lower():
            if normalized_character.isspace() or normalized_character == "\u00a0":
                continue
            characters.append(normalized_character)
            original_offsets.append(original_offset)
    return "".join(characters), tuple(original_offsets)


def _find_evidence(parsed: ParsedDocument, expected_text: str) -> tuple[int, str] | None:
    expected = _normalized_text(expected_text)
    if not expected:
        return None
    for page in parsed.pages:
        normalized_page, offsets = _normalized_text_with_offsets(page.text)
        match_start = normalized_page.find(expected)
        if match_start >= 0:
            match_end = match_start + len(expected) - 1
            return page.number, page.text[offsets[match_start] : offsets[match_end] + 1]
    return None


class RevisedContractService:
    def __init__(
        self,
        *,
        repository: RevisedContractRepository,
        documents: DocumentRepository,
        storage: PrivateStorage,
        parser: DocumentAnalysisAdapter,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._documents = documents
        self._storage = storage
        self._parser = parser
        self._now = now or (lambda: datetime.now(UTC))

    async def create_review(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        payload: RevisedContractReviewCreate,
    ) -> RevisedContractReview:
        document = await self._documents.get_owned_document(
            owner_id=owner_id,
            contract_id=contract_id,
            document_id=payload.document_id,
        )
        if document is None:
            raise ResourceNotFound()
        if document.type != DocumentType.REVISED_CONTRACT:
            raise InvalidDocument("수정 계약서 대조에는 REVISED_CONTRACT PDF가 필요합니다.")
        latest = await self._documents.get_latest_owned_document(
            owner_id=owner_id,
            contract_id=contract_id,
            document_type=DocumentType.REVISED_CONTRACT,
        )
        if latest is None or latest.id != document.id:
            raise InvalidDocument("가장 최근에 업로드한 수정 계약서만 대조할 수 있습니다.")
        context = await self._repository.get_revised_contract_context(
            owner_id=owner_id,
            contract_id=contract_id,
            adjustment_request_id=payload.adjustment_request_id,
        )
        if context is None or not context.final_clauses:
            raise InvalidStatusTransition(
                "확정된 조정 결과가 있어야 수정 계약서를 대조할 수 있습니다."
            )
        content = await self._storage.download_private_object(path=document.storage_path)
        parsed = await self._parser.parse_document(
            content=content,
            content_type=document.content_type,
        )
        items: list[RevisedContractReviewItem] = []
        for clause in context.final_clauses:
            evidence = _find_evidence(parsed, clause.after_text)
            items.append(
                RevisedContractReviewItem(
                    review_item_id=clause.review_item_id,
                    expected_text=clause.after_text,
                    match_status=(
                        RevisedContractMatchStatus.MATCHED
                        if evidence
                        else RevisedContractMatchStatus.NEEDS_CONFIRMATION
                    ),
                    source_page=evidence[0] if evidence else None,
                    source_text=evidence[1] if evidence else None,
                    confidence=1.0 if evidence else None,
                )
            )
        review = RevisedContractReview(
            id=uuid4(),
            contract_id=contract_id,
            adjustment_request_id=payload.adjustment_request_id,
            document_id=document.id,
            document_sha256=hashlib.sha256(content).hexdigest(),
            status=RevisedContractReviewStatus.REVIEW_REQUIRED,
            items=items,
            created_at=self._utc_now(),
        )
        saved = await self._repository.create_revised_contract_review_with_audit(
            owner_id=owner_id,
            review=review,
        )
        if saved is None:
            raise InvalidStatusTransition("수정 계약서 대조를 시작할 수 없는 상태입니다.")
        return saved

    async def get_latest(self, *, owner_id: UUID, contract_id: UUID) -> RevisedContractReview:
        review = await self._repository.get_latest_owned_revised_contract_review(
            owner_id=owner_id,
            contract_id=contract_id,
        )
        if review is None:
            raise ResourceNotFound()
        return review

    async def confirm(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        review_id: UUID,
        payload: RevisedContractReviewConfirmation,
    ) -> RevisedContractReview:
        confirmed = await self._repository.confirm_revised_contract_review_with_audit(
            owner_id=owner_id,
            contract_id=contract_id,
            review_id=review_id,
            confirmed_review_item_ids=tuple(payload.confirmed_review_item_ids),
            confirmed_at=self._utc_now(),
        )
        if confirmed is None:
            raise InvalidStatusTransition("최신 수정 계약서의 모든 대조 항목을 확인해야 합니다.")
        return confirmed

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("Revision timestamps must be timezone-aware.")
        return value.astimezone(UTC)
