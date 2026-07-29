from enum import StrEnum


class ContractStatus(StrEnum):
    DRAFT = "DRAFT"
    ANALYZING = "ANALYZING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NEGOTIATING = "NEGOTIATING"
    READY_TO_SIGN = "READY_TO_SIGN"
    SIGNING = "SIGNING"
    SIGNED = "SIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RENEWAL_DUE = "RENEWAL_DUE"


class AdjustmentRequestStatus(StrEnum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    OPENED = "OPENED"
    RESPONDED = "RESPONDED"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"


class ModusignStatus(StrEnum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ON_PROCESSING = "ON_PROCESSING"
    ON_GOING = "ON_GOING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    PROCESSING_FAILED = "PROCESSING_FAILED"


class InternalSignatureStatus(StrEnum):
    REQUEST_READY = "REQUEST_READY"
    REQUESTING = "REQUESTING"
    SIGNING = "SIGNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


class ObligationStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"


class VerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NOT_FOUND = "NOT_FOUND"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    NEEDS_CHECK = "NEEDS_CHECK"


class ReviewSignalType(StrEnum):
    MISMATCH = "MISMATCH"
    NO_BASIS = "NO_BASIS"
    UNCLEAR = "UNCLEAR"
    MISSING = "MISSING"
    NEEDS_CHECK = "NEEDS_CHECK"


class ReviewSeverity(StrEnum):
    INFO = "INFO"
    CHECK = "CHECK"
    IMPORTANT = "IMPORTANT"


class SuggestionChoice(StrEnum):
    ACCEPT = "ACCEPT"
    COMPROMISE = "COMPROMISE"
    REQUEST = "REQUEST"


class ExtractedField(StrEnum):
    CONTRACT_PARTY_OWNER = "contract_party_owner"
    CONTRACT_PARTY_AGENCY = "contract_party_agency"
    CONTRACT_START_DATE = "contract_start_date"
    CONTRACT_END_DATE = "contract_end_date"
    MONTHLY_AMOUNT = "monthly_amount"
    CONTRACT_TOTAL_AMOUNT = "contract_total_amount"
    PAYMENT_METHOD = "payment_method"
    AUTO_RENEWAL = "auto_renewal"
    TERMINATION_NOTICE_DATE = "termination_notice_date"
    EARLY_TERMINATION_ALLOWED = "early_termination_allowed"
    TERMINATION_PENALTY_RATE = "termination_penalty_rate"
    REFUND_CONDITION = "refund_condition"
    ADVERTISING_CHANNEL = "advertising_channel"
    CONTENT_TYPE = "content_type"
    CONTENT_QUANTITY = "content_quantity"
    POSTING_FREQUENCY = "posting_frequency"
    REPORTING_FREQUENCY = "reporting_frequency"
    PERFORMANCE_GUARANTEE = "performance_guarantee"
    CONTENT_OWNERSHIP = "content_ownership"
    PORTRAIT_RIGHTS = "portrait_rights"
    FACILITY_DAMAGE_LIABILITY = "facility_damage_liability"
    FALSE_ADVERTISING_LIABILITY = "false_advertising_liability"


class ExtractedValueType(StrEnum):
    TEXT = "TEXT"
    DATE = "DATE"
    MONEY_KRW = "MONEY_KRW"
    INTEGER = "INTEGER"
    PERCENT = "PERCENT"
    BOOLEAN = "BOOLEAN"


class DetectionMethod(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    MODEL = "MODEL"
    HYBRID = "HYBRID"
