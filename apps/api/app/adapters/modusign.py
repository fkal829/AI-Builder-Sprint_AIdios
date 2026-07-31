import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

import httpx

from app.schemas.agreements import Agreement
from app.schemas.signatures import SignatureSigner


class ModusignAdapterError(RuntimeError):
    """A vendor request failed without exposing the vendor response."""


@dataclass(frozen=True)
class ModusignEmbeddedDraft:
    id: str
    editor_url: str
    expires_at: datetime


class ModusignAdapter:
    """Translate our signing request into the isolated Modusign API boundary."""

    _base_url = "https://api.modusign.co.kr"

    def __init__(
        self,
        *,
        account_email: str,
        api_key: str,
        mode: Literal["mock", "live"],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._account_email = account_email
        self._api_key = api_key
        self._mode = mode
        self._client = client

    async def create_embedded_draft(
        self,
        *,
        agreement: Agreement,
        agreement_pdf: bytes,
        signers: list[SignatureSigner],
        redirect_url: str,
    ) -> ModusignEmbeddedDraft:
        if self._mode == "mock":
            draft_id = f"mock-modusign-draft-{uuid4()}"
            return ModusignEmbeddedDraft(
                id=draft_id,
                editor_url=f"https://mock.modusign.local/embedded-draft/{draft_id}",
                expires_at=datetime.now(UTC) + timedelta(hours=2),
            )
        payload: dict[str, Any] = {
            "title": f"{agreement.title} v{agreement.version}",
            "file": {
                "base64": base64.b64encode(agreement_pdf).decode("ascii"),
                "extension": "pdf",
            },
            "participants": [
                {
                    "type": "SIGNER",
                    "role": signer.role,
                    "name": signer.name,
                    "signingOrder": 1,
                    "signingMethod": signer.signing_method.model_dump(),
                }
                for signer in signers
            ],
        }
        if redirect_url:
            payload["redirectUrl"] = redirect_url
        response_data = await self._request(
            "POST",
            "/embedded-drafts",
            json=payload,
        )
        try:
            expiry = datetime.fromisoformat(str(response_data["expiry"]).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                raise ValueError("expiry must include a timezone")
            return ModusignEmbeddedDraft(
                id=str(response_data["id"]),
                editor_url=str(response_data["embeddedUrl"]),
                expires_at=expiry.astimezone(UTC),
            )
        except (KeyError, ValueError, TypeError) as error:
            raise ModusignAdapterError("The vendor response had an unsupported shape.") from error

    async def _request(self, method: str, path: str, *, json: dict[str, Any]) -> dict[str, Any]:
        encoded = base64.b64encode(
            f"{self._account_email}:{self._api_key}".encode()
        ).decode("ascii")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
        }
        try:
            if self._client is not None:
                response = await self._client.request(method, path, headers=headers, json=json)
            else:
                async with httpx.AsyncClient(base_url=self._base_url, timeout=15.0) as client:
                    response = await client.request(method, path, headers=headers, json=json)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ModusignAdapterError("The vendor request failed.") from error
        if not isinstance(payload, dict):
            raise ModusignAdapterError("The vendor response had an unsupported shape.")
        return payload
