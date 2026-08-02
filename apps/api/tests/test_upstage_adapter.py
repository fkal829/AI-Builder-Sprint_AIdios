import json
import logging

import httpx
import pytest

from app.adapters.base import ParsedDocument, ParsedElement, ParsedPage
from app.adapters.upstage import (
    DOCUMENT_PARSE_PATH,
    UNIVERSAL_EXTRACTION_PATH,
    UpstageAdapter,
    UpstageExtractionError,
    _information_extract_schema,
    _parsed_document_from_document_parse,
)
from app.core.enums import ExtractedField, VerificationStatus


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeAsyncClient:
    calls: list[tuple[str, dict]] = []
    response_payload: dict = {}

    def __init__(self, **_kwargs) -> None:
        pass

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def post(
        self,
        path: str,
        *,
        json: dict | None = None,
        files=None,
        data=None,
    ) -> FakeResponse:
        request_body = json if json is not None else {"files": files, "data": data}
        self.calls.append((path, request_body))
        return FakeResponse(self.response_payload)


def test_information_extract_schema_rejects_unknown_fields() -> None:
    schema = _information_extract_schema((ExtractedField.MONTHLY_AMOUNT,))

    assert schema["additionalProperties"] is False


async def test_live_extract_rejects_unrequested_result_field(monkeypatch) -> None:
    FakeAsyncClient.calls = []
    FakeAsyncClient.response_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "monthly_amount": 500000,
                            "invented_admin_override": "yes",
                        }
                    ),
                    "tool_calls": [],
                }
            }
        ]
    }
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    adapter = UpstageAdapter(
        api_key="test-key",
        base_url="https://api.upstage.ai",
        mode="live",
    )

    with pytest.raises(UpstageExtractionError):
        await adapter.extract_terms(
            content=b"%PDF-test",
            content_type="application/pdf",
            parsed_document=ParsedDocument(
                pages=(ParsedPage(number=1, text="월 대행료는 500,000원이다."),),
                model="document-parse",
            ),
            target_fields=(ExtractedField.MONTHLY_AMOUNT,),
        )


def test_document_parse_keeps_pages_elements_and_coordinates() -> None:
    parsed = _parsed_document_from_document_parse(
        {
            "model": "document-parse",
            "elements": [
                {
                    "page": 1,
                    "content": {"text": "계약기간은 2026년 8월 1일부터로 한다."},
                    "coordinates": [
                        {"x": 0.1, "y": 0.1},
                        {"x": 0.9, "y": 0.1},
                        {"x": 0.9, "y": 0.2},
                        {"x": 0.1, "y": 0.2},
                    ],
                }
            ],
        }
    )

    assert parsed.model == "document-parse"
    assert parsed.pages[0].number == 1
    assert parsed.elements[0].coordinates[0] == (0.1, 0.1)


async def test_live_extract_uses_single_pdf_item_and_builtin_evidence_metadata(
    monkeypatch,
    caplog,
) -> None:
    caplog.set_level(logging.INFO, logger="app.adapters.upstage")
    FakeAsyncClient.calls = []
    FakeAsyncClient.response_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"contract_start_date": "2026-08-01"},
                        ensure_ascii=False,
                    ),
                    "tool_calls": [
                        {
                            "function": {
                                "name": "additional_values",
                                "arguments": json.dumps(
                                    {
                                        "contract_start_date": {
                                            "_value": "2026-08-01",
                                            "confidence": "high",
                                            "page": 1,
                                            "coordinates": [
                                                {"x": 0.2, "y": 0.12},
                                                {"x": 0.4, "y": 0.12},
                                                {"x": 0.4, "y": 0.18},
                                                {"x": 0.2, "y": 0.18},
                                            ],
                                        }
                                    }
                                ),
                            }
                        }
                    ],
                }
            }
        ]
    }
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    evidence = "계약기간은 2026년 8월 1일부터로 한다."
    parsed = ParsedDocument(
        pages=(ParsedPage(number=1, text=evidence),),
        model="document-parse",
        elements=(
            ParsedElement(
                page=1,
                text=evidence,
                coordinates=(
                    (0.1, 0.1),
                    (0.9, 0.1),
                    (0.9, 0.2),
                    (0.1, 0.2),
                ),
            ),
        ),
    )
    adapter = UpstageAdapter(
        api_key="test-key",
        base_url="https://api.upstage.ai",
        mode="live",
    )

    terms = await adapter.extract_terms(
        content=b"%PDF-test",
        content_type="application/pdf",
        parsed_document=parsed,
        target_fields=(ExtractedField.CONTRACT_START_DATE,),
    )

    path, body = FakeAsyncClient.calls[0]
    assert path == UNIVERSAL_EXTRACTION_PATH
    assert len(body["messages"][0]["content"]) == 1
    assert body["messages"][0]["content"][0]["image_url"]["url"].startswith(
        "data:application/octet-stream;base64,"
    )
    assert body["location"] is True
    assert body["confidence"] is True
    assert terms[0].verification_status == VerificationStatus.VERIFIED
    assert terms[0].source_page == 1
    assert terms[0].source_text == evidence
    assert terms[0].confidence == 0.9
    log_text = caplog.text
    assert "upstage_extract_run" in log_text
    assert "model=information-extract" in log_text
    assert "status=completed" in log_text
    assert "latency_ms=" in log_text
    assert "schema_valid=True" in log_text
    assert "test-key" not in log_text
    assert evidence not in log_text
    assert "%PDF-test" not in log_text


async def test_live_extract_isolates_malformed_date_in_many_blanks_result(
    monkeypatch,
) -> None:
    FakeAsyncClient.calls = []
    evidence = "송도체험공방과 가상기획사는 2026년 4월 1일부터 2027년 3월 31일까지 계약한다."
    coordinates = [
        {"x": 0.1, "y": 0.1},
        {"x": 0.9, "y": 0.1},
        {"x": 0.9, "y": 0.2},
        {"x": 0.1, "y": 0.2},
    ]
    FakeAsyncClient.response_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "contract_start_date": "2026-04-01",
                            "contract_end_date": "2027년 3월 31일",
                        },
                        ensure_ascii=False,
                    ),
                    "tool_calls": [
                        {
                            "function": {
                                "name": "additional_values",
                                "arguments": json.dumps(
                                    {
                                        "contract_start_date": {
                                            "_value": "2026-04-01",
                                            "confidence": "high",
                                            "page": 1,
                                            "coordinates": coordinates,
                                        },
                                        "contract_end_date": {
                                            "_value": "2027년 3월 31일",
                                            "confidence": "high",
                                            "page": 1,
                                            "coordinates": coordinates,
                                        },
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        }
                    ],
                }
            }
        ]
    }
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    parsed = ParsedDocument(
        pages=(ParsedPage(number=1, text=evidence),),
        model="document-parse",
        elements=(
            ParsedElement(
                page=1,
                text=evidence,
                coordinates=((0.1, 0.1), (0.9, 0.1), (0.9, 0.2), (0.1, 0.2)),
            ),
        ),
    )
    target_fields = (
        ExtractedField.CONTRACT_START_DATE,
        ExtractedField.CONTRACT_END_DATE,
        ExtractedField.CONTENT_QUANTITY,
        ExtractedField.DELIVERABLE_DUE_DATE,
        ExtractedField.REPORTING_FREQUENCY,
        ExtractedField.SHOOTING_SAFETY,
    )
    adapter = UpstageAdapter(
        api_key="test-key",
        base_url="https://api.upstage.ai",
        mode="live",
    )

    terms = await adapter.extract_terms(
        content=b"%PDF-test",
        content_type="application/pdf",
        parsed_document=parsed,
        target_fields=target_fields,
    )

    assert [term.field for term in terms] == list(target_fields)
    terms_by_field = {term.field: term for term in terms}
    start_date = terms_by_field[ExtractedField.CONTRACT_START_DATE]
    assert start_date.value == "2026-04-01"
    assert start_date.verification_status == VerificationStatus.VERIFIED
    assert start_date.source_page == 1
    assert start_date.source_text == evidence

    malformed_end_date = terms_by_field[ExtractedField.CONTRACT_END_DATE]
    assert malformed_end_date.value is None
    assert malformed_end_date.verification_status == VerificationStatus.NEEDS_CHECK
    assert malformed_end_date.source_page == 1
    assert malformed_end_date.source_text == evidence
    assert malformed_end_date.confidence == 0.9

    omitted_fields = target_fields[2:]
    assert all(
        terms_by_field[field].value is None
        and terms_by_field[field].verification_status == VerificationStatus.NOT_FOUND
        and terms_by_field[field].source_page is None
        and terms_by_field[field].source_text is None
        for field in omitted_fields
    )


async def test_live_extract_marks_malformed_date_without_evidence_as_not_found(
    monkeypatch,
) -> None:
    FakeAsyncClient.calls = []
    FakeAsyncClient.response_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"contract_end_date": "2027년 3월 31일"},
                        ensure_ascii=False,
                    ),
                    "tool_calls": [],
                }
            }
        ]
    }
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    adapter = UpstageAdapter(
        api_key="test-key",
        base_url="https://api.upstage.ai",
        mode="live",
    )

    terms = await adapter.extract_terms(
        content=b"%PDF-test",
        content_type="application/pdf",
        parsed_document=ParsedDocument(
            pages=(ParsedPage(number=1, text="계약 종료일은 원문에 없다."),),
            model="document-parse",
        ),
        target_fields=(ExtractedField.CONTRACT_END_DATE,),
    )

    assert len(terms) == 1
    assert terms[0].field == ExtractedField.CONTRACT_END_DATE
    assert terms[0].value is None
    assert terms[0].verification_status == VerificationStatus.NOT_FOUND
    assert terms[0].source_page is None
    assert terms[0].source_text is None
    assert terms[0].confidence == 0


async def test_live_parse_logs_safe_metadata_without_document_or_response(
    monkeypatch,
    caplog,
) -> None:
    caplog.set_level(logging.INFO, logger="app.adapters.upstage")
    secret_text = "외부에 남기면 안 되는 계약 원문"
    FakeAsyncClient.calls = []
    FakeAsyncClient.response_payload = {
        "model": "document-parse",
        "elements": [
            {
                "page": 1,
                "content": {"text": secret_text},
            }
        ],
    }
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    adapter = UpstageAdapter(
        api_key="private-upstage-key",
        base_url="https://api.upstage.ai",
        mode="live",
    )

    parsed = await adapter.parse_document(
        content=b"%PDF-private-contract",
        content_type="application/pdf",
    )

    assert FakeAsyncClient.calls[0][0] == DOCUMENT_PARSE_PATH
    assert parsed.pages[0].text == secret_text
    log_text = caplog.text
    assert "upstage_parse_run" in log_text
    assert "model=document-parse" in log_text
    assert "status=completed" in log_text
    assert "http_status=200" in log_text
    assert "latency_ms=" in log_text
    assert "schema_valid=True" in log_text
    assert "private-upstage-key" not in log_text
    assert secret_text not in log_text
    assert "%PDF-private-contract" not in log_text


async def test_live_extract_schema_failure_logs_no_payload(
    monkeypatch,
    caplog,
) -> None:
    caplog.set_level(logging.INFO, logger="app.adapters.upstage")
    secret_payload = "response-body-must-not-be-logged"
    FakeAsyncClient.calls = []
    FakeAsyncClient.response_payload = {"unexpected": secret_payload}
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    adapter = UpstageAdapter(
        api_key="private-upstage-key",
        base_url="https://api.upstage.ai",
        mode="live",
    )

    with pytest.raises(UpstageExtractionError):
        await adapter.extract_terms(
            content=b"%PDF-private-contract",
            content_type="application/pdf",
            parsed_document=ParsedDocument(
                pages=(ParsedPage(number=1, text="민감한 원문"),),
                model="document-parse",
            ),
            target_fields=(ExtractedField.MONTHLY_AMOUNT,),
        )

    log_text = caplog.text
    assert "upstage_extract_run" in log_text
    assert "status=failed" in log_text
    assert "schema_valid=False" in log_text
    assert "private-upstage-key" not in log_text
    assert secret_payload not in log_text
    assert "민감한 원문" not in log_text


async def test_live_extract_marks_value_without_matching_location_as_missing_evidence(
    monkeypatch,
) -> None:
    FakeAsyncClient.calls = []
    FakeAsyncClient.response_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"monthly_amount": 500000}),
                    "tool_calls": [
                        {
                            "function": {
                                "name": "additional_values",
                                "arguments": json.dumps(
                                    {
                                        "monthly_amount": {
                                            "_value": 500000,
                                            "confidence": "low",
                                            "page": 1,
                                            "coordinates": [
                                                {"x": 0.7, "y": 0.7},
                                                {"x": 0.8, "y": 0.7},
                                                {"x": 0.8, "y": 0.8},
                                                {"x": 0.7, "y": 0.8},
                                            ],
                                        }
                                    }
                                ),
                            }
                        }
                    ],
                }
            }
        ]
    }
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    parsed = ParsedDocument(
        pages=(ParsedPage(number=1, text="월 대행료는 500,000원이다."),),
        model="document-parse",
        elements=(
            ParsedElement(
                page=1,
                text="월 대행료는 500,000원이다.",
                coordinates=((0.1, 0.1), (0.4, 0.1), (0.4, 0.2), (0.1, 0.2)),
            ),
        ),
    )
    adapter = UpstageAdapter(
        api_key="test-key",
        base_url="https://api.upstage.ai",
        mode="live",
    )

    terms = await adapter.extract_terms(
        content=b"%PDF-test",
        content_type="application/pdf",
        parsed_document=parsed,
        target_fields=(ExtractedField.MONTHLY_AMOUNT,),
    )

    assert terms[0].value == 500000
    assert terms[0].verification_status == VerificationStatus.MISSING_EVIDENCE
    assert terms[0].source_page is None
    assert terms[0].source_text is None
    assert terms[0].confidence == 0.4


async def test_live_extract_keeps_low_confidence_evidence_as_needs_check(
    monkeypatch,
) -> None:
    FakeAsyncClient.calls = []
    FakeAsyncClient.response_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"monthly_amount": 500000}),
                    "tool_calls": [
                        {
                            "function": {
                                "name": "additional_values",
                                "arguments": json.dumps(
                                    {
                                        "monthly_amount": {
                                            "_value": 500000,
                                            "confidence": "low",
                                            "page": 1,
                                            "coordinates": [
                                                {"x": 0.2, "y": 0.12},
                                                {"x": 0.3, "y": 0.12},
                                                {"x": 0.3, "y": 0.18},
                                                {"x": 0.2, "y": 0.18},
                                            ],
                                        }
                                    }
                                ),
                            }
                        }
                    ],
                }
            }
        ]
    }
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    evidence = "월 대행료는 500,000원이다."
    parsed = ParsedDocument(
        pages=(ParsedPage(number=1, text=evidence),),
        model="document-parse",
        elements=(
            ParsedElement(
                page=1,
                text=evidence,
                coordinates=((0.1, 0.1), (0.4, 0.1), (0.4, 0.2), (0.1, 0.2)),
            ),
        ),
    )
    adapter = UpstageAdapter(
        api_key="test-key",
        base_url="https://api.upstage.ai",
        mode="live",
    )

    terms = await adapter.extract_terms(
        content=b"%PDF-test",
        content_type="application/pdf",
        parsed_document=parsed,
        target_fields=(ExtractedField.MONTHLY_AMOUNT,),
    )

    assert terms[0].verification_status == VerificationStatus.NEEDS_CHECK
    assert terms[0].source_page == 1
    assert terms[0].source_text == evidence
    assert terms[0].confidence == 0.4
