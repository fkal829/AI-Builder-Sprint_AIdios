from datetime import date
from io import BytesIO
from uuid import uuid4

from pypdf import PdfReader

from app.schemas.agreements import (
    Agreement,
    AgreementClause,
    AgreementConditionSummary,
    OriginalContractReference,
)
from app.services.agreement_pdf import AgreementPdfRenderer


def test_renders_confirmed_agreement_to_in_memory_pdf() -> None:
    agreement = Agreement.model_construct(
        id=uuid4(),
        version=1,
        title="Agreement",
        original_contract=OriginalContractReference(
            title="Original contract",
            signed_date=date(2026, 7, 1),
            document_id=uuid4(),
        ),
        condition_summary=AgreementConditionSummary(
            term_and_payment="Term",
            deliverables_and_reporting="Deliverables",
            termination_and_renewal="Renewal",
            rights_safety_and_liability="Safety",
        ),
        clauses=[
            AgreementClause.model_construct(
                review_item_id=uuid4(),
                category="TERM_AND_PAYMENT",
                outcome="AGREED",
                disposition="AGREED",
                before="Before",
                after="After",
                reason=None,
            )
        ],
        unchanged_terms_policy="Unchanged terms remain effective.",
        signature_roles=["OWNER", "AGENCY"],
    )

    pdf = AgreementPdfRenderer().render(agreement)

    assert pdf.startswith(b"%PDF-")
    assert len(PdfReader(BytesIO(pdf)).pages) >= 1
