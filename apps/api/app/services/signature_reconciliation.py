"""On-read, best-effort sync with Modusign for a signature the webhook (C-8)
may never have reached (no publicly reachable callback URL in local/dev,
delivery failure, ...).

Reuses the same idempotent ``apply_modusign_document_status`` RPC the webhook
handler applies, so calling this repeatedly never re-applies an
already-applied transition or duplicates an audit event. A vendor lookup
failure here must never break the read it is attached to; the caller always
gets back at least the last known record.
"""

import hmac
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from app.adapters.modusign import ModusignAdapter, ModusignAdapterError, ModusignDocumentStatus
from app.core.enums import InternalSignatureStatus
from app.core.exceptions import ExternalStorageFailure
from app.repositories.signatures import SignatureRecord, SignatureRepository
from app.services.webhooks import ModusignWebhookService

_TERMINAL_SIGNATURE_STATUSES = {
    InternalSignatureStatus.COMPLETED,
    InternalSignatureStatus.ABORTED,
    InternalSignatureStatus.FAILED,
}
_SIGNATURE_ID_METADATA_KEY = "aidos_signature_id"
_SIGNATURE_PROOF_METADATA_KEY = "aidos_signature_proof"


class SignatureReconciler:
    def __init__(
        self,
        *,
        repository: SignatureRepository,
        modusign: ModusignAdapter,
        webhook_secret: str = "",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._modusign = modusign
        self._webhook_secret = webhook_secret
        self._now = now or (lambda: datetime.now(UTC))
        # Request-scoped: one listing serves every pending signature in a
        # contract-list read instead of one vendor call per contract.
        self._recent_documents: list[ModusignDocumentStatus] | None = None

    async def reconcile_owned(
        self, *, owner_id: UUID, contract_id: UUID
    ) -> SignatureRecord | None:
        record = await self._repository.get_latest_owned_signature(
            owner_id=owner_id, contract_id=contract_id
        )
        if record is None:
            return None
        return await self.reconcile(owner_id=owner_id, record=record)

    async def reconcile(self, *, owner_id: UUID, record: SignatureRecord) -> SignatureRecord:
        signature = record.signature
        if signature.status in _TERMINAL_SIGNATURE_STATUSES:
            return record
        try:
            document = await self._current_document(record)
            if document is None:
                return record
            applied = await self._repository.apply_modusign_document_status(
                signature_id=signature.id,
                document_id=document.id,
                event_key=f"poll:{document.id}:{document.status.value}",
                status=document.status,
                processed_at=self._utc_now(),
            )
        except (ExternalStorageFailure, ModusignAdapterError):
            # Best-effort: a vendor hiccup must not break reading the last
            # known status. The next read, or a webhook, retries this.
            return record
        if not applied:
            return record
        refreshed = await self._repository.get_latest_owned_signature(
            owner_id=owner_id, contract_id=record.signature.contract_id
        )
        return refreshed or record

    async def _current_document(self, record: SignatureRecord) -> ModusignDocumentStatus | None:
        """Resolve the Modusign document backing this signature.

        Only a webhook ever supplies ``modusign_document_id``. Until one
        arrives we cannot derive it: an embedded draft's id is a different
        identifier from the document that draft becomes once sent, and the
        vendor offers no draft-to-document lookup (querying /documents with a
        draft id is rejected). So fall back to finding the document by the
        metadata we attached when creating the draft.
        """
        signature = record.signature
        if signature.modusign_document_id is not None:
            return await self._modusign.get_document_status(
                document_id=signature.modusign_document_id
            )
        if self._recent_documents is None:
            self._recent_documents = await self._modusign.list_recent_documents()
        for document in self._recent_documents:
            if self._identifies(document, signature_id=signature.id):
                return document
        return None

    def _identifies(self, document: ModusignDocumentStatus, *, signature_id: UUID) -> bool:
        """Trust vendor metadata only when it carries our own HMAC proof.

        Mirrors the webhook's verification rather than matching on the id
        alone, so a document we did not create cannot claim a signature.
        """
        if document.metadata.get(_SIGNATURE_ID_METADATA_KEY) != str(signature_id):
            return False
        proof = document.metadata.get(_SIGNATURE_PROOF_METADATA_KEY)
        if not proof or not self._webhook_secret:
            return False
        expected = ModusignWebhookService.build_signature_metadata(
            signature_id=signature_id,
            webhook_secret=self._webhook_secret,
        )[_SIGNATURE_PROOF_METADATA_KEY]
        return hmac.compare_digest(proof, expected)

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("Signature timestamps must be timezone-aware.")
        return value.astimezone(UTC)
