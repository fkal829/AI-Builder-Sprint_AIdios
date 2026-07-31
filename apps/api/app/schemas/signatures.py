from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.enums import InternalSignatureStatus, ModusignStatus


class EmailSignatureMethod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["EMAIL"]
    value: str = Field(min_length=3, max_length=254)

    @field_validator("value")
    @classmethod
    def has_email_shape(cls, value: str) -> str:
        local, separator, domain = value.rpartition("@")
        if not separator or not local or "." not in domain or domain.startswith("."):
            raise ValueError("A valid email address is required.")
        return value


class KakaoSignatureMethod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["KAKAO"]
    value: str = Field(pattern=r"^01[016789][0-9]{7,8}$")


SignatureMethod = Annotated[
    EmailSignatureMethod | KakaoSignatureMethod,
    Field(discriminator="type"),
]


class SignatureSigner(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["OWNER", "AGENCY"]
    name: str = Field(min_length=2, max_length=30)
    signing_method: SignatureMethod


class EmbeddedSignatureDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revised_contract_review_id: UUID | None = None
    agreement_id: UUID | None = None
    agreement_version: int | None = Field(default=None, ge=1)
    signers: list[SignatureSigner] = Field(min_length=2, max_length=2)
    confirmed: Literal[True]

    @model_validator(mode="after")
    def has_exactly_one_signer_per_role_and_contact(self) -> "EmbeddedSignatureDraftCreate":
        roles = [signer.role for signer in self.signers]
        contacts = [signer.signing_method.value for signer in self.signers]
        if set(roles) != {"OWNER", "AGENCY"} or len(set(roles)) != 2:
            raise ValueError("Exactly one OWNER and one AGENCY signer are required.")
        if len(set(contacts)) != len(contacts):
            raise ValueError("Signer contacts must not be duplicated.")
        uses_revision = self.revised_contract_review_id is not None
        uses_legacy_agreement = self.agreement_id is not None or self.agreement_version is not None
        if uses_revision == uses_legacy_agreement:
            raise ValueError(
                "Provide a revised_contract_review_id or a legacy agreement ID/version, not both."
            )
        if uses_legacy_agreement and (
            self.agreement_id is None or self.agreement_version is None
        ):
            raise ValueError("Legacy agreement ID and version must be supplied together.")
        return self


class EmbeddedSignatureDraft(BaseModel):
    """A short-lived Modusign editor link; never persist or log `editor_url`."""

    signature: "Signature"
    editor_url: str
    expires_at: datetime


class Signature(BaseModel):
    id: UUID
    contract_id: UUID
    status: InternalSignatureStatus
    modusign_status: ModusignStatus | None = None
    modusign_draft_id: str | None = None
    modusign_document_id: str | None = None
    last_event_id: str | None = None
    requested_at: datetime | None = None
    completed_at: datetime | None = None
