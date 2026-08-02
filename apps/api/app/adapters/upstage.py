import base64
import json
import logging
import re
from collections import defaultdict
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from app.adapters.base import ParsedDocument, ParsedElement, ParsedPage
from app.core.enums import ExtractedField, ExtractedValueType, VerificationStatus
from app.schemas.analysis import (
    EXPECTED_VALUE_TYPES,
    ExtractedTermCandidate,
)

DOCUMENT_PARSE_PATH = "/v1/document-digitization"
UNIVERSAL_EXTRACTION_PATH = "/v1/information-extraction/chat/completions"
MOCK_PARSE_MODEL = "mock-document-parse-v1"
MOCK_EXTRACT_MODEL = "mock-information-extract-v1"
HIGH_CONFIDENCE = 0.9
LOW_CONFIDENCE = 0.4
LOW_CONFIDENCE_THRESHOLD = 0.5
logger = logging.getLogger(__name__)

_ABSENCE_MENTION_ENDING = r"않(?:다|습니다|았다|았습니다|는다|음|지만|았지만|고|으나|았으나)"
_REFUND_SUBJECT_PATTERN = (
    r"(?:환불(?:조건|조항|규정|기준)|"
    r"환불에관한(?:별도)?(?:조건|조항|규정|기준))"
)
_REFUND_SUBJECT_BRIDGE = (
    r"(?:은|는|이|가|을|를)?"
    r"(?:(?:본)?계약서(?:에|에는|상)?|별도로)*"
)
_REFUND_ACTION_LANGUAGE = re.compile(
    r"(?:"
    r"(?:환불|환급)(?:은|는|이|가|을|를)?"
    r"(?:하|한|했|합|함|해|되|된|됐|됩|받|가능|불가|없|제한|제외)"
    r"|(?:미사용(?:기간)?|잔여(?:기간)?)(?:대금|금액).*?"
    r"(?:환불|환급|반환|돌려(?:주|준|줌|받))"
    r"|(?:환불|환급|반환|돌려(?:주|준|줌|받)).*?"
    r"(?:미사용(?:기간)?|잔여(?:기간)?)(?:대금|금액)"
    r")"
)
_UNDOCUMENTED_STATE = r"(?:미기재|미명시)(?:다|입니다|됨|되어있(?:다|습니다))?"
_REFUND_DOCUMENTATION_ABSENCE_MENTION = re.compile(
    _REFUND_SUBJECT_PATTERN
    + _REFUND_SUBJECT_BRIDGE
    + r"(?:"
    + _UNDOCUMENTED_STATE
    + r"|(?:기재|명시|규정|작성)(?:하지|되어있지|돼있지|되지)"
    + _ABSENCE_MENTION_ENDING
    + r"|정하지"
    + _ABSENCE_MENTION_ENDING
    + r"|(?:정해져있지|정해지지)"
    + _ABSENCE_MENTION_ENDING
    + r")"
)
_REFUND_SUBJECT_ABSENCE_MENTION = re.compile(
    _REFUND_SUBJECT_PATTERN
    + _REFUND_SUBJECT_BRIDGE
    + r"(?:없(?:다|습니다|음|지만)|존재하지"
    + _ABSENCE_MENTION_ENDING
    + r"|두지"
    + _ABSENCE_MENTION_ENDING
    + r")"
)

FIELD_DESCRIPTIONS: dict[ExtractedField, str] = {
    ExtractedField.CONTRACT_PARTY_OWNER: "소상공인 또는 광고주 계약 당사자명",
    ExtractedField.CONTRACT_PARTY_AGENCY: "광고대행사 계약 당사자명",
    ExtractedField.CONTRACT_SIGNED_DATE: "계약 체결일. YYYY-MM-DD",
    ExtractedField.CONTRACT_START_DATE: "계약 시작일. YYYY-MM-DD",
    ExtractedField.CONTRACT_END_DATE: "계약 종료일. YYYY-MM-DD",
    ExtractedField.MONTHLY_AMOUNT: "월 납부 금액. 대한민국 원 정수",
    ExtractedField.CONTRACT_TOTAL_AMOUNT: "총 계약 금액. 대한민국 원 정수",
    ExtractedField.PAYMENT_METHOD: "결제 방식 또는 일정",
    ExtractedField.AUTO_RENEWAL: "자동 갱신 여부. YES, NO, UNKNOWN 중 하나",
    ExtractedField.CONTRACT_RENEWAL_TYPE: "갱신 유형. AUTO, MANUAL, NONE, UNKNOWN 중 하나",
    ExtractedField.TERMINATION_NOTICE_DATE: "해지 통보 기한 날짜. YYYY-MM-DD",
    ExtractedField.EARLY_TERMINATION_ALLOWED: "중도 해지 가능 여부. YES, NO, UNKNOWN 중 하나",
    ExtractedField.TERMINATION_PENALTY_RATE: "중도 해지 위약금 비율. 0부터 100 사이 정수",
    ExtractedField.REFUND_CONDITION: (
        "실제 환불 가능 여부·대상·금액·시점·방법. "
        "'환불하지 않는다'와 '환불 불가'도 명시적인 환불 조건"
    ),
    ExtractedField.ADVERTISING_CHANNEL: "광고 채널",
    ExtractedField.CONTENT_TYPE: "제작 또는 게시할 콘텐츠 유형",
    ExtractedField.CONTENT_QUANTITY: "콘텐츠 수량 정수",
    ExtractedField.DELIVERABLE_DUE_DATE: "대표 산출물 제출 또는 게시 기한. YYYY-MM-DD",
    ExtractedField.POSTING_FREQUENCY: "게시 빈도",
    ExtractedField.REPORTING_FREQUENCY: "성과 보고 빈도",
    ExtractedField.PERFORMANCE_GUARANTEE: "성과 보장 조건",
    ExtractedField.ADVERTISING_ACCOUNT_OWNERSHIP: "광고 계정 소유권과 접근 권한",
    ExtractedField.CONTENT_OWNERSHIP: "제작 콘텐츠의 저작권 또는 소유권",
    ExtractedField.SHOOTING_SAFETY: "촬영 안전 책임과 조치",
    ExtractedField.PORTRAIT_RIGHTS: "초상권 동의와 책임",
    ExtractedField.PERSONAL_INFORMATION_HANDLING: "개인정보 수집, 이용, 보관 조건",
    ExtractedField.FACILITY_DAMAGE_LIABILITY: "시설 파손 또는 손해 책임",
    ExtractedField.FALSE_ADVERTISING_LIABILITY: "허위 또는 과장 광고 책임",
}

MOCK_EVIDENCE: dict[ExtractedField, tuple[Any, str, float]] = {
    ExtractedField.CONTRACT_START_DATE: (
        "2026-08-01",
        "계약기간은 2026년 8월 1일부터 2027년 7월 31일까지로 한다.",
        0.98,
    ),
    ExtractedField.CONTRACT_END_DATE: (
        "2027-07-31",
        "계약기간은 2026년 8월 1일부터 2027년 7월 31일까지로 한다.",
        0.98,
    ),
    ExtractedField.MONTHLY_AMOUNT: (
        500_000,
        "월 광고대행료는 500,000원이다.",
        0.97,
    ),
    ExtractedField.CONTRACT_TOTAL_AMOUNT: (
        6_000_000,
        "총 계약금액은 6,000,000원이다.",
        0.97,
    ),
    ExtractedField.REFUND_CONDITION: (
        "중도 해지 시 잔여 기간 대금은 환불하지 않는다.",
        "중도 해지 시 잔여 기간 대금은 환불하지 않는다.",
        0.95,
    ),
    ExtractedField.EARLY_TERMINATION_ALLOWED: (
        "YES",
        "계약 당사자는 30일 전에 통보하여 중도 해지할 수 있다.",
        0.95,
    ),
    ExtractedField.CONTENT_TYPE: (
        "SNS 홍보 콘텐츠",
        "대행사는 2026년 8월 20일까지 인스타그램 SNS 홍보 콘텐츠 12건을 제작한다.",
        0.94,
    ),
    ExtractedField.CONTENT_QUANTITY: (
        12,
        "대행사는 2026년 8월 20일까지 인스타그램 SNS 홍보 콘텐츠 12건을 제작한다.",
        0.94,
    ),
    ExtractedField.DELIVERABLE_DUE_DATE: (
        "2026-08-20",
        "대행사는 2026년 8월 20일까지 인스타그램 SNS 홍보 콘텐츠 12건을 제작한다.",
        0.94,
    ),
    ExtractedField.ADVERTISING_CHANNEL: (
        "인스타그램",
        "대행사는 2026년 8월 20일까지 인스타그램 SNS 홍보 콘텐츠 12건을 제작한다.",
        0.94,
    ),
    ExtractedField.SHOOTING_SAFETY: (
        "촬영 시 현장 안전수칙을 준수한다.",
        "촬영 시 현장 안전수칙을 준수한다.",
        0.92,
    ),
    ExtractedField.FACILITY_DAMAGE_LIABILITY: (
        "대행사의 과실로 발생한 시설 파손은 대행사가 배상한다.",
        "대행사의 과실로 발생한 시설 파손은 대행사가 배상한다.",
        0.92,
    ),
    ExtractedField.FALSE_ADVERTISING_LIABILITY: (
        "허위·과장 광고 문구는 게시 전에 상호 확인한다.",
        "허위·과장 광고 문구는 게시 전에 상호 확인한다.",
        0.91,
    ),
}


class UpstageDocumentParseError(RuntimeError):
    pass


class UpstageExtractionError(RuntimeError):
    pass


def _http_status_from_error(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    return status_code if isinstance(status_code, int) else None


def _log_upstage_run(
    *,
    run_type: str,
    model: str,
    started_at: str,
    started: float,
    status: str,
    http_status: int | None,
    schema_valid: bool,
) -> None:
    logger.info(
        "upstage_%s_run model=%s started_at=%s status=%s http_status=%s "
        "latency_ms=%d schema_valid=%s",
        run_type,
        model,
        started_at,
        status,
        http_status,
        round((perf_counter() - started) * 1000),
        schema_valid,
    )


class UpstageAdapter:
    """Upstage Document Parse and Information Extract boundary."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        mode: Literal["mock", "live"],
        parse_timeout_seconds: float = 120,
        extract_timeout_seconds: float = 180,
        extract_model: str = "information-extract",
    ) -> None:
        if mode == "live" and not api_key:
            raise ValueError("UPSTAGE_MODE=live에는 UPSTAGE_API_KEY가 필요합니다.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.mode = mode
        self.parse_timeout_seconds = parse_timeout_seconds
        self.extract_timeout_seconds = extract_timeout_seconds
        self.extract_model = extract_model

    async def parse_document(
        self,
        *,
        content: bytes,
        content_type: str,
    ) -> ParsedDocument:
        if self.mode == "mock":
            if content_type == "text/plain":
                text = content.decode("utf-8")
            else:
                text = "\n".join(evidence for _value, evidence, _score in MOCK_EVIDENCE.values())
            return ParsedDocument(
                pages=(ParsedPage(number=1, text=text),),
                model=MOCK_PARSE_MODEL,
            )

        if content_type == "text/plain":
            return ParsedDocument(
                pages=(ParsedPage(number=1, text=content.decode("utf-8")),),
                model="local-utf8-text",
            )

        started_at = datetime.now(UTC).isoformat()
        started = perf_counter()
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.parse_timeout_seconds,
                headers={"Authorization": f"Bearer {self.api_key}"},
            ) as client:
                response = await client.post(
                    DOCUMENT_PARSE_PATH,
                    files={"document": ("document", content, content_type)},
                    data={"ocr": "auto", "model": "document-parse"},
                )
                response.raise_for_status()
        except (httpx.HTTPError, ValueError) as error:
            _log_upstage_run(
                run_type="parse",
                model="document-parse",
                started_at=started_at,
                started=started,
                status="failed",
                http_status=_http_status_from_error(error),
                schema_valid=False,
            )
            raise UpstageDocumentParseError("문서 구조 분석에 실패했습니다.") from error

        try:
            payload = response.json()
            parsed_document = _parsed_document_from_document_parse(payload)
            if not parsed_document.pages:
                raise ValueError("Document Parse returned no page text.")
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            _log_upstage_run(
                run_type="parse",
                model="document-parse",
                started_at=started_at,
                started=started,
                status="failed",
                http_status=getattr(response, "status_code", 200),
                schema_valid=False,
            )
            raise UpstageDocumentParseError("문서 구조 분석 결과가 올바르지 않습니다.") from error
        _log_upstage_run(
            run_type="parse",
            model=parsed_document.model,
            started_at=started_at,
            started=started,
            status="completed",
            http_status=getattr(response, "status_code", 200),
            schema_valid=True,
        )
        return parsed_document

    async def extract_terms(
        self,
        *,
        content: bytes,
        content_type: str,
        parsed_document: ParsedDocument,
        target_fields: tuple[ExtractedField, ...],
    ) -> list[ExtractedTermCandidate]:
        if self.mode == "mock":
            return _mock_terms(target_fields)

        started_at = datetime.now(UTC).isoformat()
        started = perf_counter()
        document_url = _document_data_url(content=content, content_type=content_type)
        if document_url is None:
            _log_upstage_run(
                run_type="extract",
                model=self.extract_model,
                started_at=started_at,
                started=started,
                status="failed",
                http_status=None,
                schema_valid=False,
            )
            raise UpstageExtractionError("Universal Extraction에서 처리할 수 없는 문서 형식입니다.")
        schema = _information_extract_schema(target_fields)
        body = {
            "model": self.extract_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": document_url},
                        }
                    ],
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "contract_terms",
                    "schema": schema,
                },
            },
            "location": True,
            "location_granularity": "element",
            "confidence": True,
            "split": False,
        }

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.extract_timeout_seconds,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            ) as client:
                response = await client.post(UNIVERSAL_EXTRACTION_PATH, json=body)
                response.raise_for_status()
        except (httpx.HTTPError, ValueError) as error:
            _log_upstage_run(
                run_type="extract",
                model=self.extract_model,
                started_at=started_at,
                started=started,
                status="failed",
                http_status=_http_status_from_error(error),
                schema_valid=False,
            )
            raise UpstageExtractionError("계약 필드 추출에 실패했습니다.") from error

        try:
            payload = response.json()
            message = payload["choices"][0]["message"]
            content_json = message["content"]
            extracted = json.loads(content_json)
            additional_values = _additional_values(message)
            candidates = _candidates_from_information_extract(
                extracted=extracted,
                additional_values=additional_values,
                target_fields=target_fields,
                parsed_document=parsed_document,
            )
        except (
            IndexError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            ValidationError,
        ) as error:
            _log_upstage_run(
                run_type="extract",
                model=self.extract_model,
                started_at=started_at,
                started=started,
                status="failed",
                http_status=getattr(response, "status_code", 200),
                schema_valid=False,
            )
            raise UpstageExtractionError("계약 필드 추출 결과가 스키마와 맞지 않습니다.") from error
        _log_upstage_run(
            run_type="extract",
            model=self.extract_model,
            started_at=started_at,
            started=started,
            status="completed",
            http_status=getattr(response, "status_code", 200),
            schema_valid=True,
        )
        return candidates


def _parsed_document_from_document_parse(payload: dict[str, Any]) -> ParsedDocument:
    page_parts: dict[int, list[str]] = defaultdict(list)
    parsed_elements: list[ParsedElement] = []
    elements = payload.get("elements")
    if isinstance(elements, list):
        for element in elements:
            if not isinstance(element, dict):
                continue
            page = element.get("page")
            text = _content_text(element.get("content"))
            if isinstance(page, int) and page >= 1 and text:
                page_parts[page].append(text)
                coordinates = _coordinates(element.get("coordinates"))
                if coordinates:
                    parsed_elements.append(
                        ParsedElement(
                            page=page,
                            text=text,
                            coordinates=coordinates,
                        )
                    )
    return ParsedDocument(
        pages=tuple(
            ParsedPage(number=page, text="\n".join(parts))
            for page, parts in sorted(page_parts.items())
        ),
        model=str(payload.get("model") or "document-parse"),
        elements=tuple(parsed_elements),
    )


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        for key in ("text", "markdown", "html"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                if key == "html":
                    return re.sub(r"<[^>]+>", " ", value).strip()
                return value.strip()
    return ""


def _mock_terms(
    target_fields: tuple[ExtractedField, ...],
) -> list[ExtractedTermCandidate]:
    terms: list[ExtractedTermCandidate] = []
    for field in target_fields:
        evidence = MOCK_EVIDENCE.get(field)
        if evidence is None:
            continue
        value, source_text, confidence = evidence
        terms.append(
            ExtractedTermCandidate(
                field=field,
                value_type=EXPECTED_VALUE_TYPES.get(field, ExtractedValueType.TEXT),
                value=value,
                source_page=1,
                source_text=source_text,
                confidence=confidence,
                verification_status=VerificationStatus.VERIFIED,
            )
        )
    return terms


def _document_data_url(*, content: bytes, content_type: str) -> str | None:
    if content_type not in {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "text/plain",
    }:
        return None
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:application/octet-stream;base64,{encoded}"


def _information_extract_schema(
    target_fields: tuple[ExtractedField, ...],
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for field in target_fields:
        value_type = EXPECTED_VALUE_TYPES.get(field, ExtractedValueType.TEXT)
        if value_type in {
            ExtractedValueType.MONEY_KRW,
            ExtractedValueType.INTEGER,
            ExtractedValueType.PERCENT,
        }:
            property_type = "integer"
        else:
            property_type = "string"
        omission_guidance = ""
        if field == ExtractedField.REFUND_CONDITION:
            omission_guidance = (
                "'기재하지 않았다', '명시하지 않았다', "
                "'작성하지 않았다' 또는 '정하지 않았다'는 부재 설명만 "
                "있으면 그 문장을 값으로 추출하지 말고 이 속성을 결과에서 생략. "
            )
        properties[field.value] = {
            "type": property_type,
            "description": (
                f"{FIELD_DESCRIPTIONS[field]}. {omission_guidance}"
                "문서에서 실제 조건이 확인되지 않으면 이 속성을 결과에서 생략"
            ),
        }
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }


def _additional_values(message: dict[str, Any]) -> dict[str, Any]:
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return {}
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function")
        if not isinstance(function, dict) or function.get("name") != "additional_values":
            continue
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            continue
        decoded = json.loads(arguments)
        if isinstance(decoded, dict):
            return decoded
    return {}


def _candidates_from_information_extract(
    *,
    extracted: dict[str, Any],
    additional_values: dict[str, Any],
    target_fields: tuple[ExtractedField, ...],
    parsed_document: ParsedDocument,
) -> list[ExtractedTermCandidate]:
    if not isinstance(extracted, dict):
        raise ValueError("Information Extract result must be an object.")
    expected_fields = {field.value for field in target_fields}
    unexpected_fields = set(extracted) - expected_fields
    if unexpected_fields:
        raise ValueError("Information Extract result contains unexpected fields.")
    pages = {page.number: page.text for page in parsed_document.pages}
    candidates: list[ExtractedTermCandidate] = []
    for field in target_fields:
        value_type = EXPECTED_VALUE_TYPES.get(field, ExtractedValueType.TEXT)
        metadata = additional_values.get(field.value)
        if not isinstance(metadata, dict):
            metadata = {}
        confidence = _numeric_confidence(metadata.get("confidence"))
        source_page = metadata.get("page")
        source_text = _source_text_from_location(
            parsed_document=parsed_document,
            page=source_page,
            coordinates=metadata.get("coordinates"),
        )

        has_evidence = (
            isinstance(source_page, int)
            and not isinstance(source_page, bool)
            and source_page in pages
            and isinstance(source_text, str)
            and bool(source_text.strip())
            and _contains_evidence(pages[source_page], source_text)
        )
        if has_evidence:
            source_text = source_text.strip()
        else:
            source_page = None
            source_text = None

        raw_value = extracted.get(field.value)
        if field == ExtractedField.REFUND_CONDITION:
            refund_absence = _classify_explicit_refund_absence(
                value=raw_value,
                source_text=source_text,
            )
            if refund_absence == "not_found":
                candidates.append(_not_found_value_candidate(field=field, value_type=value_type))
                continue
            if refund_absence == "needs_check":
                candidates.append(
                    _invalid_value_candidate(
                        field=field,
                        value_type=value_type,
                        source_page=source_page,
                        source_text=source_text,
                        confidence=confidence,
                    )
                )
                continue

        try:
            value = _normalize_value(
                field=field,
                value_type=value_type,
                value=raw_value,
            )
        except ValueError:
            candidates.append(
                _invalid_value_candidate(
                    field=field,
                    value_type=value_type,
                    source_page=source_page,
                    source_text=source_text,
                    confidence=confidence,
                )
            )
            continue

        if value is None:
            status = VerificationStatus.NOT_FOUND
            source_page = None
            source_text = None
        elif has_evidence:
            status = VerificationStatus.VERIFIED
        else:
            status = VerificationStatus.MISSING_EVIDENCE

        if status == VerificationStatus.VERIFIED and confidence <= LOW_CONFIDENCE_THRESHOLD:
            status = VerificationStatus.NEEDS_CHECK

        if (
            field
            in {
                ExtractedField.AUTO_RENEWAL,
                ExtractedField.EARLY_TERMINATION_ALLOWED,
                ExtractedField.CONTRACT_RENEWAL_TYPE,
            }
            and value == "UNKNOWN"
        ):
            status = VerificationStatus.NEEDS_CHECK
            if source_page is None or source_text is None:
                status = VerificationStatus.MISSING_EVIDENCE

        try:
            candidate = ExtractedTermCandidate(
                field=field,
                value_type=value_type,
                value=value,
                source_page=source_page,
                source_text=source_text,
                confidence=confidence,
                verification_status=status,
            )
        except ValidationError:
            if value is None:
                raise
            candidate = _invalid_value_candidate(
                field=field,
                value_type=value_type,
                source_page=source_page,
                source_text=source_text,
                confidence=confidence,
            )
        candidates.append(candidate)
    return candidates


def _invalid_value_candidate(
    *,
    field: ExtractedField,
    value_type: ExtractedValueType,
    source_page: int | None,
    source_text: str | None,
    confidence: float,
) -> ExtractedTermCandidate:
    if source_page is not None and source_text is not None:
        return ExtractedTermCandidate(
            field=field,
            value_type=value_type,
            value=None,
            source_page=source_page,
            source_text=source_text,
            confidence=confidence,
            verification_status=VerificationStatus.NEEDS_CHECK,
        )
    return _not_found_value_candidate(field=field, value_type=value_type)


def _not_found_value_candidate(
    *,
    field: ExtractedField,
    value_type: ExtractedValueType,
) -> ExtractedTermCandidate:
    return ExtractedTermCandidate(
        field=field,
        value_type=value_type,
        value=None,
        source_page=None,
        source_text=None,
        confidence=0,
        verification_status=VerificationStatus.NOT_FOUND,
    )


def _classify_explicit_refund_absence(
    *,
    value: Any,
    source_text: str | None,
) -> Literal["none", "not_found", "needs_check"]:
    if not isinstance(value, str) or source_text is None:
        return "none"

    found_absence = False
    found_conflict = False
    for sentence in re.split(r"[.!?\n]+", source_text):
        compact_sentence = _compact_semantic_text(sentence)
        if not compact_sentence:
            continue
        has_absence = bool(
            _REFUND_DOCUMENTATION_ABSENCE_MENTION.search(compact_sentence)
            or _REFUND_SUBJECT_ABSENCE_MENTION.search(compact_sentence)
        )
        if has_absence:
            found_absence = True
        if _REFUND_ACTION_LANGUAGE.search(compact_sentence):
            found_conflict = True

    if not found_absence:
        return "none"
    if found_conflict:
        return "needs_check"
    return "not_found"


def _compact_semantic_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value).lower()


def _coordinates(value: Any) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, list):
        return ()
    points: list[tuple[float, float]] = []
    for point in value:
        if not isinstance(point, dict):
            return ()
        x = point.get("x")
        y = point.get("y")
        if (
            not isinstance(x, int | float)
            or isinstance(x, bool)
            or not isinstance(y, int | float)
            or isinstance(y, bool)
        ):
            return ()
        points.append((float(x), float(y)))
    return tuple(points)


def _source_text_from_location(
    *,
    parsed_document: ParsedDocument,
    page: Any,
    coordinates: Any,
) -> str | None:
    if not isinstance(page, int) or page < 1:
        return None
    location = _coordinates(coordinates)
    if not location:
        return None
    location_box = _bounding_box(location)
    location_center = (
        (location_box[0] + location_box[2]) / 2,
        (location_box[1] + location_box[3]) / 2,
    )
    ranked: list[tuple[int, int, float, ParsedElement]] = []
    for element in parsed_document.elements:
        if element.page != page or not element.coordinates:
            continue
        element_box = _bounding_box(element.coordinates)
        contains_center = int(
            element_box[0] <= location_center[0] <= element_box[2]
            and element_box[1] <= location_center[1] <= element_box[3]
        )
        overlaps = int(_boxes_overlap(location_box, element_box))
        distance = ((element_box[0] + element_box[2]) / 2 - location_center[0]) ** 2 + (
            (element_box[1] + element_box[3]) / 2 - location_center[1]
        ) ** 2
        ranked.append((contains_center, overlaps, -distance, element))
    if not ranked:
        return None
    contains, overlaps, _distance, best = max(
        ranked,
        key=lambda item: (item[0], item[1], item[2]),
    )
    if not contains and not overlaps:
        return None
    return best.text.strip() or None


def _bounding_box(
    coordinates: tuple[tuple[float, float], ...],
) -> tuple[float, float, float, float]:
    xs = [point[0] for point in coordinates]
    ys = [point[1] for point in coordinates]
    return min(xs), min(ys), max(xs), max(ys)


def _boxes_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return not (
        first[2] < second[0] or second[2] < first[0] or first[3] < second[1] or second[3] < first[1]
    )


def _numeric_confidence(value: Any) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return min(max(float(value), 0), 1)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "high":
            return HIGH_CONFIDENCE
        if normalized == "low":
            return LOW_CONFIDENCE
    return 0


def _normalize_value(
    *,
    field: ExtractedField,
    value_type: ExtractedValueType,
    value: Any,
) -> Any:
    if value is None:
        return None
    if value_type in {
        ExtractedValueType.MONEY_KRW,
        ExtractedValueType.INTEGER,
        ExtractedValueType.PERCENT,
    }:
        if isinstance(value, bool):
            raise ValueError(f"{field.value} must be an integer.")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            digits = re.sub(r"[^0-9-]", "", value)
            if digits and digits != "-":
                return int(digits)
        raise ValueError(f"{field.value} must be an integer.")
    if not isinstance(value, str):
        raise ValueError(f"{field.value} must be a string.")
    normalized = value.strip()
    if not normalized:
        return None
    if value_type == ExtractedValueType.BOOLEAN:
        normalized = normalized.upper()
    if field == ExtractedField.CONTRACT_RENEWAL_TYPE:
        normalized = normalized.upper()
    return normalized


def _contains_evidence(page_text: str, source_text: str) -> bool:
    def normalize(value: str) -> str:
        return re.sub(r"\s+", "", value)

    return normalize(source_text) in normalize(page_text)
