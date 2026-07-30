from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.core.enums import PublicTokenScope


@dataclass(frozen=True)
class PublicTokenRecord:
    id: UUID
    token_hash: str
    scope: PublicTokenScope
    resource_id: UUID
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class PublicTokenRepository(Protocol):
    async def create_public_token(self, *, record: PublicTokenRecord) -> PublicTokenRecord: ...

    async def get_public_token_by_hash(self, *, token_hash: str) -> PublicTokenRecord | None: ...
