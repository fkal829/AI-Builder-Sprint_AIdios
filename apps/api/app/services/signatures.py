import hashlib
import hmac
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.adapters.modusign import ModusignAdapter, ModusignAdapterError
from app.core.enums import InternalSignatureStatus
from app.core.exceptions import ExternalStorageFailure, ModusignRequestFailed, ResourceNotFound
from app.repositories.agreements import AgreementRepository
from app.repositories.documents import DocumentRepository, PrivateStorage
from app.repositories.revised_contracts import RevisedContractRepository
from app.repositories.signatures import SignatureRepository
from app.schemas.revised_contracts import RevisedContractReviewStatus
from app.schemas.signatures import (
    EmbeddedSignatureDraft,
    EmbeddedSignatureDraftCreate,
    Signature,
)
from app.services.signature_reconciliation import SignatureReconciler
from app.services.state_machine import InvalidStatusTransition
from app.services.webhooks import ModusignWebhookService


class SignatureService:
    def __init__(
        self,
        *,
        repository: SignatureRepository,
        agreements: AgreementRepository,
        revisions: RevisedContractRepository,
        documents: DocumentRepository,
        storage: PrivateStorage,
        modusign: ModusignAdapter,
        embedded_redirect_url: str,
        webhook_secret: str = "",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._agreements = agreements
        self._revisions = revisions
        self._documents = documents
        self._storage = storage
        self._modusign = modusign
        self._embedded_redirect_url = embedded_redirect_url
        self._webhook_secret = webhook_secret
        self._now = now or (lambda: datetime.now(UTC))
        self._reconciler = SignatureReconciler(
            repository=repository,
            modusign=modusign,
            webhook_secret=webhook_secret,
            now=now,
        )

    async def create_embedded_draft(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        payload: EmbeddedSignatureDraftCreate,
        idempotency_key: UUID,
    ) -> EmbeddedSignatureDraft:
        revised_review_id = payload.revised_contract_review_id
        document_id = None
        document_sha256 = None
        agreement_id = payload.agreement_id
        agreement_version = payload.agreement_version
        if revised_review_id is not None:
            review = await self._revisions.get_latest_owned_revised_contract_review(
                owner_id=owner_id,
                contract_id=contract_id,
            )
            if (
                review is None
                or review.id != revised_review_id
                or review.status != RevisedContractReviewStatus.CONFIRMED
            ):
                raise InvalidStatusTransition("The latest confirmed revised contract is required.")
            document = await self._documents.get_owned_document(
                owner_id=owner_id,
                contract_id=contract_id,
                document_id=review.document_id,
            )
            if document is None:
                raise ResourceNotFound()
            document_pdf = await self._storage.download_private_object(path=document.storage_path)
            if not hmac.compare_digest(
                hashlib.sha256(document_pdf).hexdigest(), review.document_sha256
            ):
                raise ModusignRequestFailed()
            document_id = document.id
            document_sha256 = review.document_sha256
            document_title = "확인된 수정 광고대행 계약서"
        else:
            agreement_record = await self._agreements.get_owned_agreement(
                owner_id=owner_id, contract_id=contract_id
            )
            if agreement_record is None:
                raise ResourceNotFound()
            agreement = agreement_record.agreement
            if agreement.id != agreement_id or agreement.version != agreement_version:
                raise InvalidStatusTransition(
                    "The confirmed agreement ID and version are required."
                )
            document_pdf = await self._storage.download_private_object(
                path=agreement_record.pdf_storage_path
            )
            if not hmac.compare_digest(
                hashlib.sha256(document_pdf).hexdigest(), agreement_record.pdf_sha256
            ):
                raise ModusignRequestFailed()
            document_title = f"{agreement.title} v{agreement.version}"
        record = await self._repository.prepare_embedded_signature_draft(
            owner_id=owner_id,
            signature_id=uuid4(),
            contract_id=contract_id,
            revised_contract_review_id=revised_review_id,
            document_id=document_id,
            document_sha256=document_sha256,
            agreement_id=agreement_id,
            agreement_version=agreement_version,
            idempotency_key=idempotency_key,
            requested_at=self._utc_now(),
        )
        if record is None:
            raise InvalidStatusTransition(
                "The contract is not ready for an embedded signature draft."
            )
        if record.signature.status == InternalSignatureStatus.FAILED:
            raise ModusignRequestFailed()
        if record.signature.status != InternalSignatureStatus.REQUESTING:
            raise InvalidStatusTransition(
                "An embedded signature draft already exists for this idempotency key."
            )
        try:
            vendor_draft = await self._modusign.create_embedded_draft(
                document_title=document_title,
                document_pdf=document_pdf,
                signers=payload.signers,
                redirect_url=self._embedded_redirect_url,
                metadata=ModusignWebhookService.build_signature_metadata(
                    signature_id=record.signature.id,
                    webhook_secret=self._webhook_secret,
                ),
            )
        except (ExternalStorageFailure, ModusignAdapterError, OSError) as error:
            await self._repository.fail_embedded_signature_draft(
                owner_id=owner_id,
                signature_id=record.signature.id,
                completed_at=self._utc_now(),
            )
            raise ModusignRequestFailed() from error
        saved = await self._repository.complete_embedded_signature_draft(
            owner_id=owner_id,
            signature_id=record.signature.id,
            modusign_draft_id=vendor_draft.id,
        )
        if saved is None:
            raise ModusignRequestFailed()
        return EmbeddedSignatureDraft(
            signature=saved.signature,
            editor_url=vendor_draft.editor_url,
            expires_at=vendor_draft.expires_at,
        )

    async def get(self, *, owner_id: UUID, contract_id: UUID) -> Signature:
        record = await self._repository.get_latest_owned_signature(
            owner_id=owner_id, contract_id=contract_id
        )
        if record is None:
            raise ResourceNotFound()
        record = await self._reconciler.reconcile(owner_id=owner_id, record=record)
        return record.signature

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("Signature timestamps must be timezone-aware.")
        return value.astimezone(UTC)
