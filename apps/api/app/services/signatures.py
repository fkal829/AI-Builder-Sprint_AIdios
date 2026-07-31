from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.adapters.modusign import ModusignAdapter, ModusignAdapterError
from app.core.enums import InternalSignatureStatus
from app.core.exceptions import ModusignRequestFailed, ResourceNotFound
from app.repositories.agreements import AgreementRepository
from app.repositories.signatures import SignatureRepository
from app.schemas.signatures import (
    EmbeddedSignatureDraft,
    EmbeddedSignatureDraftCreate,
    Signature,
)
from app.services.agreement_pdf import AgreementPdfRenderer
from app.services.state_machine import InvalidStatusTransition


class SignatureService:
    def __init__(
        self,
        *,
        repository: SignatureRepository,
        agreements: AgreementRepository,
        modusign: ModusignAdapter,
        agreement_pdf: AgreementPdfRenderer,
        embedded_redirect_url: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._agreements = agreements
        self._modusign = modusign
        self._agreement_pdf = agreement_pdf
        self._embedded_redirect_url = embedded_redirect_url
        self._now = now or (lambda: datetime.now(UTC))

    async def create_embedded_draft(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        payload: EmbeddedSignatureDraftCreate,
        idempotency_key: UUID,
    ) -> EmbeddedSignatureDraft:
        agreement_record = await self._agreements.get_owned_agreement(
            owner_id=owner_id, contract_id=contract_id
        )
        if agreement_record is None:
            raise ResourceNotFound()
        agreement = agreement_record.agreement
        if (
            agreement.id != payload.agreement_id
            or agreement.version != payload.agreement_version
        ):
            raise InvalidStatusTransition("The confirmed agreement ID and version are required.")
        record = await self._repository.prepare_embedded_signature_draft(
            owner_id=owner_id,
            signature_id=uuid4(),
            contract_id=contract_id,
            agreement_id=agreement.id,
            agreement_version=agreement.version,
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
            agreement_pdf = self._agreement_pdf.render(agreement)
            vendor_draft = await self._modusign.create_embedded_draft(
                agreement=agreement,
                agreement_pdf=agreement_pdf,
                signers=payload.signers,
                redirect_url=self._embedded_redirect_url,
            )
        except (ModusignAdapterError, OSError) as error:
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
        return record.signature

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("Signature timestamps must be timezone-aware.")
        return value.astimezone(UTC)
