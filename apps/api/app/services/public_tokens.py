import base64
import hashlib
import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.core.enums import PublicTokenScope
from app.core.errors import ErrorCode
from app.core.exceptions import PublicTokenExpired, ResourceNotFound
from app.repositories.public_tokens import PublicTokenRecord, PublicTokenRepository

_TOKEN_PATTERN = re.compile(r"^(?P<token_id>[0-9a-f-]{36})\.(?P<signature>[A-Za-z0-9_-]{43})$")


@dataclass(frozen=True)
class IssuedPublicToken:
    token: str
    expires_at: datetime
    scope: PublicTokenScope
    resource_id: UUID


class PublicTokenService:
    """Issue and resolve opaque public tokens without storing their raw value."""

    def __init__(
        self,
        repository: PublicTokenRepository,
        *,
        signing_secret: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if len(signing_secret) < 32:
            raise ValueError("PUBLIC_TOKEN_SECRET must be at least 32 characters.")
        self._repository = repository
        self._secret = signing_secret.encode("utf-8")
        self._now = now or (lambda: datetime.now(UTC))

    async def issue_adjustment_response(
        self,
        *,
        adjustment_request_id: UUID,
        expires_at: datetime,
    ) -> IssuedPublicToken:
        issued, record = self.prepare_adjustment_response(
            adjustment_request_id=adjustment_request_id,
            expires_at=expires_at,
        )
        await self._repository.create_public_token(record=record)
        return issued

    def prepare_adjustment_response(
        self,
        *,
        adjustment_request_id: UUID,
        expires_at: datetime,
    ) -> tuple[IssuedPublicToken, PublicTokenRecord]:
        return self.prepare(
            scope=PublicTokenScope.ADJUSTMENT_RESPONSE,
            resource_id=adjustment_request_id,
            expires_at=expires_at,
        )

    async def issue(
        self,
        *,
        scope: PublicTokenScope,
        resource_id: UUID,
        expires_at: datetime,
    ) -> IssuedPublicToken:
        issued, record = self.prepare(
            scope=scope,
            resource_id=resource_id,
            expires_at=expires_at,
        )
        await self._repository.create_public_token(record=record)
        return issued

    def prepare(
        self,
        *,
        scope: PublicTokenScope,
        resource_id: UUID,
        expires_at: datetime,
    ) -> tuple[IssuedPublicToken, PublicTokenRecord]:
        now = self._utc_now()
        normalized_expiry = _as_utc(expires_at)
        if normalized_expiry <= now:
            raise ValueError("Public token expiry must be in the future.")
        token_id = uuid4()
        token = self.token_for_id(token_id)
        record = PublicTokenRecord(
            id=token_id,
            token_hash=_token_hash(token),
            scope=scope,
            resource_id=resource_id,
            expires_at=normalized_expiry,
            revoked_at=None,
            created_at=now,
        )
        return (
            IssuedPublicToken(
                token=token,
                expires_at=normalized_expiry,
                scope=scope,
                resource_id=resource_id,
            ),
            record,
        )

    async def resolve(
        self,
        *,
        token: str,
        expected_scope: PublicTokenScope,
        expected_resource_id: UUID | None = None,
    ) -> PublicTokenRecord:
        token_id = self._validate_token_format(token)
        record = await self._repository.get_public_token_by_hash(token_hash=_token_hash(token))
        if (
            record is None
            or record.id != token_id
            or record.scope != expected_scope
            or record.revoked_at is not None
            or (expected_resource_id is not None and record.resource_id != expected_resource_id)
        ):
            raise ResourceNotFound()
        if record.expires_at <= self._utc_now():
            raise PublicTokenExpired(code=_expired_code(expected_scope))
        return record

    def token_for_id(self, token_id: UUID) -> str:
        signature = hmac.new(
            self._secret,
            str(token_id).encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{token_id}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"

    def _validate_token_format(self, token: str) -> UUID:
        match = _TOKEN_PATTERN.fullmatch(token)
        if match is None:
            raise ResourceNotFound()
        try:
            token_id = UUID(match.group("token_id"))
        except ValueError as error:
            raise ResourceNotFound() from error
        if not hmac.compare_digest(token, self.token_for_id(token_id)):
            raise ResourceNotFound()
        return token_id

    def _utc_now(self) -> datetime:
        return _as_utc(self._now())


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Public token timestamps must be timezone-aware.")
    return value.astimezone(UTC)


def _expired_code(scope: PublicTokenScope) -> ErrorCode:
    if scope == PublicTokenScope.ADJUSTMENT_RESPONSE:
        return ErrorCode.ADJUSTMENT_LINK_EXPIRED
    return ErrorCode.OBLIGATION_LINK_EXPIRED
