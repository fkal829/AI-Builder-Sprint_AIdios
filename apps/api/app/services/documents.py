import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid4

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.exceptions import ExternalStorageFailure, InvalidDocument, ResourceNotFound
from app.repositories.documents import (
    ContractOwnershipRepository,
    DocumentRecord,
    DocumentRepository,
    PrivateStorage,
)
from app.schemas.documents import (
    Document,
    DocumentAccess,
    DocumentParseStatus,
    DocumentType,
)

PDF_CONTENT_TYPE = "application/pdf"
PNG_CONTENT_TYPE = "image/png"
JPEG_CONTENT_TYPE = "image/jpeg"
TEXT_CONTENT_TYPE = "text/plain"
DOCUMENT_ACCESS_TTL_SECONDS = 5 * 60


@dataclass(frozen=True)
class ValidatedDocument:
    content_type: str
    extension: str
    page_count: int


async def read_upload_content(file, *, max_size_bytes: int) -> bytes:
    content = bytearray()
    while chunk := await file.read(min(1024 * 1024, max_size_bytes + 1 - len(content))):
        content.extend(chunk)
        if len(content) > max_size_bytes:
            raise InvalidDocument("업로드 파일은 설정된 최대 크기를 초과할 수 없습니다.")
    if not content:
        raise InvalidDocument("빈 파일은 업로드할 수 없습니다.")
    return bytes(content)


def _normalized_content_type(declared_content_type: str | None) -> str:
    if not declared_content_type:
        raise InvalidDocument("파일의 Content-Type이 필요합니다.")
    return declared_content_type.split(";", 1)[0].strip().lower()


def _detect_content_type(content: bytes) -> tuple[str, str]:
    if content.startswith(b"%PDF-"):
        return PDF_CONTENT_TYPE, "pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG_CONTENT_TYPE, "png"
    if content.startswith(b"\xff\xd8\xff"):
        return JPEG_CONTENT_TYPE, "jpg"
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise InvalidDocument("허용되지 않은 파일 형식입니다.") from error
    if "\x00" in decoded:
        raise InvalidDocument("UTF-8 text 파일에 허용되지 않은 바이트가 있습니다.")
    return TEXT_CONTENT_TYPE, "txt"


def _pdf_page_count(content: bytes, *, max_pdf_pages: int) -> int:
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise InvalidDocument("암호화된 PDF는 업로드할 수 없습니다.")
        page_count = len(reader.pages)
    except InvalidDocument:
        raise
    except (PdfReadError, ValueError, TypeError) as error:
        raise InvalidDocument("손상되었거나 읽을 수 없는 PDF입니다.") from error
    if page_count < 1:
        raise InvalidDocument("페이지가 없는 PDF는 업로드할 수 없습니다.")
    if page_count > max_pdf_pages:
        raise InvalidDocument("PDF는 설정된 최대 페이지 수를 초과할 수 없습니다.")
    return page_count


async def validate_document(
    *,
    document_type: DocumentType,
    declared_content_type: str | None,
    content: bytes,
    max_pdf_pages: int,
) -> ValidatedDocument:
    normalized_declared = _normalized_content_type(declared_content_type)
    detected_content_type, extension = _detect_content_type(content)
    if normalized_declared != detected_content_type:
        raise InvalidDocument("선언한 Content-Type과 실제 파일 형식이 일치하지 않습니다.")

    if document_type != DocumentType.MESSAGE and detected_content_type != PDF_CONTENT_TYPE:
        raise InvalidDocument("계약서·수정 계약서·제안서·견적서는 PDF만 업로드할 수 있습니다.")
    if document_type == DocumentType.MESSAGE and detected_content_type not in {
        PDF_CONTENT_TYPE,
        PNG_CONTENT_TYPE,
        JPEG_CONTENT_TYPE,
        TEXT_CONTENT_TYPE,
    }:
        raise InvalidDocument("메시지 자료는 PDF, PNG, JPEG, UTF-8 text만 허용합니다.")

    if detected_content_type == PDF_CONTENT_TYPE:
        page_count = await asyncio.to_thread(
            _pdf_page_count,
            content,
            max_pdf_pages=max_pdf_pages,
        )
    else:
        page_count = 1
    return ValidatedDocument(
        content_type=detected_content_type,
        extension=extension,
        page_count=page_count,
    )


class DocumentUploadService:
    def __init__(
        self,
        *,
        contracts: ContractOwnershipRepository,
        documents: DocumentRepository,
        storage: PrivateStorage,
        max_size_bytes: int,
        max_pdf_pages: int,
    ) -> None:
        self.contracts = contracts
        self.documents = documents
        self.storage = storage
        self.max_size_bytes = max_size_bytes
        self.max_pdf_pages = max_pdf_pages

    async def upload(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        document_type: DocumentType,
        declared_content_type: str | None,
        content: bytes,
    ) -> Document:
        if len(content) > self.max_size_bytes:
            raise InvalidDocument("업로드 파일은 설정된 최대 크기를 초과할 수 없습니다.")
        if not await self.contracts.is_contract_owned(
            owner_id=owner_id,
            contract_id=contract_id,
        ):
            raise ResourceNotFound()

        validated = await validate_document(
            document_type=document_type,
            declared_content_type=declared_content_type,
            content=content,
            max_pdf_pages=self.max_pdf_pages,
        )
        document_id = uuid4()
        storage_path = f"{owner_id}/{contract_id}/{document_id}/source.{validated.extension}"
        record = DocumentRecord(
            id=document_id,
            contract_id=contract_id,
            type=document_type,
            parse_status=DocumentParseStatus.PENDING,
            storage_path=storage_path,
            content_type=validated.content_type,
            size_bytes=len(content),
            page_count=validated.page_count,
            created_at=datetime.now(UTC),
        )

        await self.storage.upload_private_object(
            path=storage_path,
            content=content,
            content_type=validated.content_type,
        )
        try:
            saved = await self.documents.create_document_with_audit(
                owner_id=owner_id,
                record=record,
            )
        except ExternalStorageFailure as error:
            # The metadata RPC may have committed even if its response was lost.
            # Recover by the caller-generated document ID before deciding whether
            # the already-uploaded private object is safe to delete.
            try:
                recovered = await self.documents.get_owned_document(
                    owner_id=owner_id,
                    contract_id=contract_id,
                    document_id=document_id,
                )
            except ExternalStorageFailure:
                # Commit state is still ambiguous. Preserve the source object so
                # a committed DB row can never be left pointing at deleted data.
                raise error from None

            if recovered is not None:
                if recovered != record:
                    raise ExternalStorageFailure(
                        "문서 메타데이터 저장 결과가 업로드 요청과 일치하지 않습니다."
                    ) from error
                saved = recovered
            else:
                try:
                    await self.storage.delete_private_object(path=storage_path)
                except ExternalStorageFailure as rollback_error:
                    raise ExternalStorageFailure(
                        "문서 메타데이터 저장과 Storage 롤백에 실패했습니다."
                    ) from rollback_error
                raise error
        if saved is None:
            await self.storage.delete_private_object(path=storage_path)
            raise ResourceNotFound()

        return Document(
            id=saved.id,
            contract_id=saved.contract_id,
            type=saved.type,
            parse_status=saved.parse_status,
            created_at=saved.created_at,
        )


def utc_now() -> datetime:
    return datetime.now(UTC)


class DocumentAccessService:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        storage: PrivateStorage,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.documents = documents
        self.storage = storage
        self.clock = clock

    async def get_access(
        self,
        *,
        owner_id: UUID,
        contract_id: UUID,
        document_id: UUID,
        source_page: int | None,
    ) -> DocumentAccess:
        document = await self.documents.get_owned_document(
            owner_id=owner_id,
            contract_id=contract_id,
            document_id=document_id,
        )
        if document is None:
            raise ResourceNotFound()
        if source_page is not None and not 1 <= source_page <= document.page_count:
            raise InvalidDocument("요청한 페이지가 문서 페이지 범위를 벗어났습니다.")

        issued_at = self.clock()
        access_url = await self.storage.create_signed_access_url(
            path=document.storage_path,
            expires_in_seconds=DOCUMENT_ACCESS_TTL_SECONDS,
        )
        return DocumentAccess(
            document_id=document.id,
            access_url=access_url,
            expires_at=issued_at + timedelta(seconds=DOCUMENT_ACCESS_TTL_SECONDS),
            source_page=source_page,
        )
