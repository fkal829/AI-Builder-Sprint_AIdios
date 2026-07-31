import re
from pathlib import Path

from app.core.enums import AuditEventType

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = (
    REPOSITORY_ROOT
    / "supabase"
    / "migrations"
    / "20260731010000_add_revised_contract_verification.sql"
)


def test_latest_audit_event_constraint_matches_public_enum() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    constraint = re.search(
        r"check \(event_type in \((?P<values>.*?)\)\)", migration, flags=re.DOTALL
    )
    assert constraint is not None
    persisted_event_types = set(re.findall(r"'([A-Z][A-Z_]+)'", constraint["values"]))

    assert persisted_event_types == {event_type.value for event_type in AuditEventType}
    assert "drop constraint if exists audit_events_event_type_check" in migration
    assert "add constraint audit_events_event_type_check" in migration


def test_contract_lifecycle_audit_events_are_persistable() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    for event_type in (
        AuditEventType.CONTRACT_STARTED,
        AuditEventType.CONTRACT_COMPLETED,
        AuditEventType.CONTRACT_RENEWAL_DUE,
    ):
        assert f"'{event_type.value}'" in migration
