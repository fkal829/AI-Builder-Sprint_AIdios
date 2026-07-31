import pytest

from app.core.text_safety import contains_unsafe_legal_conclusion


@pytest.mark.parametrize(
    "text",
    [
        "이 계약은 불법입니다.",
        "이 계약은 명백히 불법입니다.",
        "이 조항은 명백히 위법입니다.",
        "이 업체는 안전합니다.",
        "이 업체는 매우 안전합니다.",
        "이 대행사는 충분히 안전한 곳입니다.",
        "이 경우 승소할 수 있습니다.",
        "이 경우 반드시 승소합니다.",
        "승소가 확실합니다.",
        "이 업체는 사기입니다.",
        "이 설명이 법률 자문을 완전히 대체합니다.",
        "법률 상담은 받지 않아도 됩니다.",
    ],
)
def test_rejects_prohibited_legal_or_vendor_conclusions(text: str) -> None:
    assert contains_unsafe_legal_conclusion([text]) is True


@pytest.mark.parametrize(
    "text",
    [
        "업체의 촬영 안전 책임을 확인하세요.",
        "대행사 안전 조치가 계약에 없습니다.",
        "업체의 사기 예방 책임을 확인하세요.",
        "승소 가능성을 판단하지 않습니다.",
        "법률 자문을 대체하지 않습니다.",
        "법률 상담을 받아 확인하세요.",
    ],
)
def test_allows_safety_duties_and_non_judgment_disclaimers(text: str) -> None:
    assert contains_unsafe_legal_conclusion([text]) is False
