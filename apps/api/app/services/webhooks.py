"""Idempotent Modusign webhook acceptance and deferred state reconciliation."""

import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID

from app.adapters.modusign import ModusignAdapter, ModusignAdapterError
from app.core.exceptions import ExternalStorageFailure
from app.repositories.webhooks import ModusignWebhookReceipt, ModusignWebhookRepository
from app.schemas.webhooks import ModusignWebhookEvent

_SIGNATURE_ID_METADATA_KEY = "aidos_signature_id"
_SIGNATURE_PROOF_METADATA_KEY = "aidos_signature_proof"


class ModusignWebhookService:
    def __init__(
        self,
        *,
        repository: ModusignWebhookRepository,
        modusign: ModusignAdapter,
        webhook_secret: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._modusign = modusign
        self._webhook_secret = webhook_secret
        self._now = now or (lambda: datetime.now(UTC))

    def verify_secret(self, provided_secret: str | None) -> bool:
        return bool(self._webhook_secret) and bool(provided_secret) and hmac.compare_digest(
            self._webhook_secret, provided_secret
        )

    def signature_metadata(self, signature_id: UUID) -> dict[str, str]:
        return self.build_signature_metadata(
            signature_id=signature_id,
            webhook_secret=self._webhook_secret,
        )

    @staticmethod
    def build_signature_metadata(*, signature_id: UUID, webhook_secret: str) -> dict[str, str]:
        return {
            _SIGNATURE_ID_METADATA_KEY: str(signature_id),
            _SIGNATURE_PROOF_METADATA_KEY: hmac.new(
                webhook_secret.encode("utf-8"),
                str(signature_id).encode("ascii"),
                hashlib.sha256,
            ).hexdigest(),
        }

    async def receive(self, *, payload: ModusignWebhookEvent) -> ModusignWebhookReceipt | None:
        receipt = ModusignWebhookReceipt(
            deduplication_key=self._deduplication_key(payload),
            event_id=payload.event.id,
            event_type=payload.event.type,
            document_id=payload.document.id,
            received_at=self._utc_now(),
        )
        if not await self._repository.record_modusign_webhook_event(receipt=receipt):
            return None
        return receipt

    async def process(self, *, receipt: ModusignWebhookReceipt) -> None:
        """Never let deferred vendor failures change the webhook acknowledgement."""

        try:
            document = await self._modusign.get_document_status(document_id=receipt.document_id)
            signature_id = self._verified_signature_id(document.metadata)
            if signature_id is not None:
                await self._repository.apply_modusign_document_status(
                    signature_id=signature_id,
                    document_id=document.id,
                    event_key=receipt.deduplication_key,
                    status=document.status,
                    processed_at=self._utc_now(),
                )
        except (ExternalStorageFailure, ModusignAdapterError):
            # The vendor can retry delivery. We intentionally do not expose or log
            # its response body, nor start another signature request.
            pass
        finally:
            try:
                await self._repository.mark_modusign_webhook_processed(
                    deduplication_key=receipt.deduplication_key,
                    processed_at=self._utc_now(),
                )
            except ExternalStorageFailure:
                # The acknowledgement has already been returned. Never leak the
                # persistence failure to the vendor or create another signature.
                pass

    def _verified_signature_id(self, metadata: Mapping[str, str]) -> UUID | None:
        raw_signature_id = metadata.get(_SIGNATURE_ID_METADATA_KEY)
        proof = metadata.get(_SIGNATURE_PROOF_METADATA_KEY)
        if raw_signature_id is None or proof is None:
            return None
        try:
            signature_id = UUID(raw_signature_id)
        except ValueError:
            return None
        if not hmac.compare_digest(proof, self._signature_proof(signature_id)):
            return None
        return signature_id

    def _signature_proof(self, signature_id: UUID) -> str:
        return hmac.new(
            self._webhook_secret.encode("utf-8"),
            str(signature_id).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _deduplication_key(payload: ModusignWebhookEvent) -> str:
        if payload.event.id:
            return f"event:{payload.event.id}"
        canonical = json.dumps(
            payload.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "payload:" + hashlib.sha256(canonical).hexdigest()

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("Webhook timestamps must be timezone-aware.")
        return value.astimezone(UTC)
