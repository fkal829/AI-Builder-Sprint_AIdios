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
    _classify_explicit_refund_absence,
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


def test_information_extract_schema_distinguishes_refund_omission_from_no_refund() -> None:
    schema = _information_extract_schema((ExtractedField.REFUND_CONDITION,))

    description = schema["properties"]["refund_condition"]["description"]
    assert "기재하지 않았다" in description
    assert "생략" in description
    assert "환불 불가" in description
    assert "추출" in description


@pytest.mark.parametrize(
    "refund_omission",
    [
        "환불 조건은 미기재다.",
        "환불 조건은 미기재되어 있다.",
        "환불 조건이 정해지지 않았다.",
    ],
)
def test_refund_absence_classifier_supports_equivalent_omission_phrases(
    refund_omission: str,
) -> None:
    assert (
        _classify_explicit_refund_absence(
            value=refund_omission,
            source_text=refund_omission,
        )
        == "not_found"
    )


@pytest.mark.parametrize(
    "substantive_condition",
    [
        "미사용 기간 대금은 반환한다.",
        "미사용 기간 대금은 돌려준다.",
        "미사용 기간 대금은 환급한다.",
        "전액 환불한다.",
        "전액 환급한다.",
        "결제액은 환불된다.",
        "전액 환불합니다.",
        "결제액은 환불됩니다.",
    ],
)
def test_refund_absence_classifier_preserves_synonym_mixed_evidence(
    substantive_condition: str,
) -> None:
    refund_omission = "환불 조건은 계약서에 기재하지 않았다."

    assert (
        _classify_explicit_refund_absence(
            value=refund_omission,
            source_text=f"{refund_omission} {substantive_condition}",
        )
        == "needs_check"
    )


def test_refund_absence_classifier_checks_a_mixed_full_model_value() -> None:
    mixed_value = "환불 조건은 계약서에 기재하지 않았다. 다만 미사용 기간 대금은 환불한다."

    assert (
        _classify_explicit_refund_absence(
            value=mixed_value,
            source_text=mixed_value,
        )
        == "needs_check"
    )


def test_refund_absence_classifier_checks_action_before_same_sentence_omission() -> None:
    mixed_value = "미사용 기간 대금은 환불하지만, 구체적인 환불 조건은 계약서에 기재하지 않았다."

    assert (
        _classify_explicit_refund_absence(
            value=mixed_value,
            source_text=mixed_value,
        )
        == "needs_check"
    )


@pytest.mark.parametrize(
    "non_condition_text",
    [
        "제8조 환불 조건.",
        "환불 관련 문의는 고객센터로 한다.",
        "계약 종료 시 원본 서류를 반환한다.",
    ],
)
def test_refund_absence_classifier_ignores_non_condition_context(
    non_condition_text: str,
) -> None:
    refund_omission = "환불 조건은 계약서에 기재하지 않았다."

    assert (
        _classify_explicit_refund_absence(
            value=refund_omission,
            source_text=f"{non_condition_text} {refund_omission}",
        )
        == "not_found"
    )


def test_refund_absence_classifier_ignores_same_sentence_inquiry_context() -> None:
    source_text = "환불 조건은 계약서에 기재하지 않았지만, 환불 관련 문의는 고객센터로 한다."

    assert (
        _classify_explicit_refund_absence(
            value=source_text,
            source_text=source_text,
        )
        == "not_found"
    )


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


@pytest.mark.parametrize(
    "content",
    [
        '제1조 &quot;업무&quot;',
        {"text": '제1조 &#34;업무&#34;'},
        {"markdown": '제1조 &amp;quot;업무&amp;quot;'},
        {"html": '<p>제1조 &quot;업무&quot;</p>'},
    ],
)
def test_document_parse_decodes_escaped_quotation_marks(content: object) -> None:
    parsed = _parsed_document_from_document_parse(
        {
            "model": "document-parse",
            "elements": [
                {
                    "page": 1,
                    "content": content,
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

    assert parsed.pages[0].text == '제1조 "업무"'
    assert parsed.elements[0].text == '제1조 "업무"'


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


async def test_live_extract_treats_explicit_refund_omission_as_not_found_only(
    monkeypatch,
) -> None:
    FakeAsyncClient.calls = []
    evidence = (
        "별빛게스트하우스와 가상마케팅은 2026년 2월 1일부터 2027년 1월 31일까지 "
        "계약한다. 월 대행료는 400,000원이고 총액은 4,800,000원이다. "
        "중도 해지는 30일 전 통보로 가능하다. 환불 조건은 계약서에 기재하지 않았다."
    )
    refund_omission = "환불 조건은 계약서에 기재하지 않았다."
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
                            "monthly_amount": 400000,
                            "refund_condition": refund_omission,
                        },
                        ensure_ascii=False,
                    ),
                    "tool_calls": [
                        {
                            "function": {
                                "name": "additional_values",
                                "arguments": json.dumps(
                                    {
                                        "monthly_amount": {
                                            "_value": 400000,
                                            "confidence": "high",
                                            "page": 1,
                                            "coordinates": coordinates,
                                        },
                                        "refund_condition": {
                                            "_value": refund_omission,
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
    adapter = UpstageAdapter(
        api_key="test-key",
        base_url="https://api.upstage.ai",
        mode="live",
    )

    terms = await adapter.extract_terms(
        content=b"%PDF-test",
        content_type="application/pdf",
        parsed_document=parsed,
        target_fields=(
            ExtractedField.MONTHLY_AMOUNT,
            ExtractedField.REFUND_CONDITION,
        ),
    )

    terms_by_field = {term.field: term for term in terms}
    monthly_amount = terms_by_field[ExtractedField.MONTHLY_AMOUNT]
    assert monthly_amount.value == 400000
    assert monthly_amount.verification_status == VerificationStatus.VERIFIED
    assert monthly_amount.source_page == 1
    assert monthly_amount.source_text == evidence
    assert monthly_amount.confidence == 0.9

    refund = terms_by_field[ExtractedField.REFUND_CONDITION]
    assert refund.value is None
    assert refund.verification_status == VerificationStatus.NOT_FOUND
    assert refund.source_page is None
    assert refund.source_text is None
    assert refund.confidence == 0


async def test_live_extract_does_not_confirm_refund_omission_without_valid_location(
    monkeypatch,
) -> None:
    FakeAsyncClient.calls = []
    refund_omission = "환불 조건은 계약서에 기재하지 않았다."
    FakeAsyncClient.response_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"refund_condition": refund_omission},
                        ensure_ascii=False,
                    ),
                    "tool_calls": [
                        {
                            "function": {
                                "name": "additional_values",
                                "arguments": json.dumps(
                                    {
                                        "refund_condition": {
                                            "_value": refund_omission,
                                            "confidence": "high",
                                            "page": 1,
                                            "coordinates": [
                                                {"x": 0.7, "y": 0.7},
                                                {"x": 0.8, "y": 0.7},
                                                {"x": 0.8, "y": 0.8},
                                                {"x": 0.7, "y": 0.8},
                                            ],
                                        }
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
        pages=(ParsedPage(number=1, text=refund_omission),),
        model="document-parse",
        elements=(
            ParsedElement(
                page=1,
                text=refund_omission,
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
        target_fields=(ExtractedField.REFUND_CONDITION,),
    )

    assert len(terms) == 1
    assert terms[0].value == refund_omission
    assert terms[0].verification_status == VerificationStatus.MISSING_EVIDENCE
    assert terms[0].source_page is None
    assert terms[0].source_text is None
    assert terms[0].confidence == 0.9


async def test_live_extract_keeps_mixed_refund_evidence_for_user_check(
    monkeypatch,
) -> None:
    FakeAsyncClient.calls = []
    refund_omission = "환불 조건은 계약서에 기재하지 않았다."
    evidence = refund_omission + " 다만 중도 해지 시 미사용 기간 대금은 환불한다."
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
                        {"refund_condition": refund_omission},
                        ensure_ascii=False,
                    ),
                    "tool_calls": [
                        {
                            "function": {
                                "name": "additional_values",
                                "arguments": json.dumps(
                                    {
                                        "refund_condition": {
                                            "_value": refund_omission,
                                            "confidence": "high",
                                            "page": 1,
                                            "coordinates": coordinates,
                                        }
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
    adapter = UpstageAdapter(
        api_key="test-key",
        base_url="https://api.upstage.ai",
        mode="live",
    )

    terms = await adapter.extract_terms(
        content=b"%PDF-test",
        content_type="application/pdf",
        parsed_document=parsed,
        target_fields=(ExtractedField.REFUND_CONDITION,),
    )

    assert len(terms) == 1
    assert terms[0].value is None
    assert terms[0].verification_status == VerificationStatus.NEEDS_CHECK
    assert terms[0].source_page == 1
    assert terms[0].source_text == evidence
    assert terms[0].confidence == 0.9


@pytest.mark.parametrize(
    "refund_condition",
    [
        "중도 해지 시 잔여 기간 대금은 환불하지 않는다.",
        "중도 해지 시 잔여 기간 대금은 환불 불가다.",
        "환불 조건이라는 제목은 기재하지 않았지만, 미사용 기간 대금은 환불한다.",
        "환불 조건을 수정하지 않았다.",
    ],
)
async def test_live_extract_keeps_substantive_refund_terms_verified(
    monkeypatch,
    refund_condition: str,
) -> None:
    FakeAsyncClient.calls = []
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
                        {"refund_condition": refund_condition},
                        ensure_ascii=False,
                    ),
                    "tool_calls": [
                        {
                            "function": {
                                "name": "additional_values",
                                "arguments": json.dumps(
                                    {
                                        "refund_condition": {
                                            "_value": refund_condition,
                                            "confidence": "high",
                                            "page": 1,
                                            "coordinates": coordinates,
                                        }
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
        pages=(ParsedPage(number=1, text=refund_condition),),
        model="document-parse",
        elements=(
            ParsedElement(
                page=1,
                text=refund_condition,
                coordinates=((0.1, 0.1), (0.9, 0.1), (0.9, 0.2), (0.1, 0.2)),
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
        target_fields=(ExtractedField.REFUND_CONDITION,),
    )

    assert len(terms) == 1
    assert terms[0].value == refund_condition
    assert terms[0].verification_status == VerificationStatus.VERIFIED
    assert terms[0].source_page == 1
    assert terms[0].source_text == refund_condition
    assert terms[0].confidence == 0.9


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
