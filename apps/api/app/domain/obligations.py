from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.core.enums import (
    ExtractedField,
    ExtractedSourceType,
    VerificationStatus,
)
from app.schemas.analysis import ExtractedTerm

REPRESENTATIVE_TITLE_FIELDS = (
    ExtractedField.ADVERTISING_CHANNEL,
    ExtractedField.CONTENT_TYPE,
    ExtractedField.CONTENT_QUANTITY,
)
REPRESENTATIVE_OBLIGATION_FIELDS = (
    *REPRESENTATIVE_TITLE_FIELDS,
    ExtractedField.DELIVERABLE_DUE_DATE,
)


@dataclass(frozen=True)
class RepresentativeObligationDraft:
    contract_id: UUID
    title: str
    due_date: date
    source_document_id: UUID
    source_page: int
    source_text: str
    confidence: float


def build_representative_obligation(
    *,
    contract_id: UUID,
    terms: Sequence[ExtractedTerm],
) -> RepresentativeObligationDraft | None:
    """Build the one P0 obligation only from one coherent contract excerpt."""

    verified_contract_terms = [
        term
        for term in terms
        if term.contract_id == contract_id
        and term.source_type == ExtractedSourceType.CONTRACT_DOCUMENT
        and term.verification_status == VerificationStatus.VERIFIED
    ]
    due_terms = [
        term
        for term in verified_contract_terms
        if term.field == ExtractedField.DELIVERABLE_DUE_DATE
    ]
    if len(due_terms) != 1:
        return None
    due = due_terms[0]
    if due.source_page is None or due.source_text is None:
        return None

    title_terms: list[ExtractedTerm] = []
    for field in REPRESENTATIVE_TITLE_FIELDS:
        matches = [
            term
            for term in verified_contract_terms
            if term.field == field
            and term.document_id == due.document_id
            and term.source_page == due.source_page
            and term.source_text == due.source_text
        ]
        if len(matches) != 1:
            return None
        title_terms.append(matches[0])

    values = {
        term.field: (
            f"{term.value}건"
            if term.field == ExtractedField.CONTENT_QUANTITY
            else str(term.value).strip()
        )
        for term in title_terms
    }
    title = " ".join(values[field] for field in REPRESENTATIVE_TITLE_FIELDS if field in values)
    if not title:
        return None

    return RepresentativeObligationDraft(
        contract_id=contract_id,
        title=title,
        due_date=date.fromisoformat(str(due.value)),
        source_document_id=due.document_id,
        source_page=due.source_page,
        source_text=due.source_text,
        confidence=min(term.confidence for term in (due, *title_terms)),
    )
