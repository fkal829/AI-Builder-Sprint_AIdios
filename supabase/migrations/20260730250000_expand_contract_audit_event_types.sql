-- Align the persisted AuditEvent allow-list with the P0 API contract.
-- The initial table constraint omitted the three deterministic contract
-- lifecycle events even though they are public AuditEventType values.

alter table public.audit_events
    drop constraint if exists audit_events_event_type_check;

alter table public.audit_events
    add constraint audit_events_event_type_check
    check (
        event_type in (
            'CONTRACT_CREATED',
            'CONTRACT_STARTED',
            'CONTRACT_COMPLETED',
            'CONTRACT_RENEWAL_DUE',
            'DOCUMENT_UPLOADED',
            'UNDERSTOOD_TERMS_SAVED',
            'ANALYSIS_STARTED',
            'ANALYSIS_RESTARTED',
            'ANALYSIS_COMPLETED',
            'ANALYSIS_FAILED',
            'REVIEW_ITEM_SELECTION_UPDATED',
            'ADJUSTMENT_DRAFT_CREATED',
            'ADJUSTMENT_SENT',
            'ADJUSTMENT_OPENED',
            'ADJUSTMENT_RESPONDED',
            'ADJUSTMENT_CONFIRMED',
            'ADJUSTMENT_EXPIRED',
            'AGREEMENT_CREATED',
            'SIGNATURE_REQUESTED',
            'SIGNATURE_STARTED',
            'SIGNATURE_COMPLETED',
            'SIGNATURE_ABORTED',
            'SIGNATURE_FAILED',
            'OBLIGATION_CREATED',
            'EVIDENCE_LINK_CREATED',
            'EVIDENCE_SUBMITTED',
            'EVIDENCE_APPROVED',
            'EVIDENCE_DISPUTED',
            'RENEWAL_DECISION_SAVED'
        )
    );
