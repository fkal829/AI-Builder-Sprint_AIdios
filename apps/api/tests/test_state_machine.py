import json
from uuid import uuid4

import pytest
from starlette.requests import Request

from app.core.enums import (
    AdjustmentRequestStatus,
    AnalysisStatus,
    AuditActorType,
    AuditEventType,
    ContractStatus,
    InternalSignatureStatus,
    ModusignStatus,
    ObligationStatus,
)
from app.main import invalid_status_transition_handler
from app.services.state_machine import (
    ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS,
    ALLOWED_ANALYSIS_TASK_TRANSITIONS,
    ALLOWED_CONTRACT_TRANSITIONS,
    ALLOWED_INTERNAL_SIGNATURE_TRANSITIONS,
    ALLOWED_MODUSIGN_TRANSITIONS,
    ALLOWED_OBLIGATION_TRANSITIONS,
    AUDIT_RULES,
    AnalysisCompletionTransition,
    AuditEventInput,
    InvalidStatusTransition,
    StateMachineService,
    StateTransition,
    ensure_contract_transition,
    ensure_transition,
)


class FakeStateTransitionRepository:
    def __init__(self, *, apply_transition: bool = True) -> None:
        self.apply_transition = apply_transition
        self.transitions: list[StateTransition] = []
        self.analysis_completions: list[AnalysisCompletionTransition] = []

    async def transition_with_audit(self, *, transition: StateTransition) -> bool:
        self.transitions.append(transition)
        return self.apply_transition

    async def complete_analysis_with_audit(
        self,
        *,
        transition: AnalysisCompletionTransition,
    ) -> bool:
        self.analysis_completions.append(transition)
        return self.apply_transition


def _audit_event() -> AuditEventInput:
    return AuditEventInput(
        event_type=AuditEventType.ANALYSIS_STARTED,
        actor_type=AuditActorType.OWNER,
        summary="분석을 시작했습니다.",
    )


def test_allows_expected_contract_transition() -> None:
    ensure_contract_transition(ContractStatus.DRAFT, ContractStatus.ANALYZING)


def test_rejects_skipped_contract_transition() -> None:
    with pytest.raises(InvalidStatusTransition):
        ensure_contract_transition(ContractStatus.DRAFT, ContractStatus.SIGNED)


def test_allows_signature_failure_to_return_contract_to_ready_to_sign() -> None:
    ensure_contract_transition(ContractStatus.SIGNING, ContractStatus.READY_TO_SIGN)


def test_every_allowed_edge_has_an_audit_rule() -> None:
    transition_sets = {
        "CONTRACT": ALLOWED_CONTRACT_TRANSITIONS,
        "ADJUSTMENT_REQUEST": ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS,
        "INTERNAL_SIGNATURE": ALLOWED_INTERNAL_SIGNATURE_TRANSITIONS,
        "OBLIGATION": ALLOWED_OBLIGATION_TRANSITIONS,
        "ANALYSIS_TASK": ALLOWED_ANALYSIS_TASK_TRANSITIONS,
    }

    for entity_type, transitions in transition_sets.items():
        for current, targets in transitions.items():
            for target in targets:
                assert any(
                    rule_entity_type.value == entity_type
                    and rule_current == current
                    and rule_target == target
                    for (rule_entity_type, rule_current, rule_target) in AUDIT_RULES
                )


@pytest.mark.parametrize(
    ("current", "target", "transitions"),
    [
        (
            AdjustmentRequestStatus.SENT,
            AdjustmentRequestStatus.RESPONDED,
            ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS,
        ),
        (
            AdjustmentRequestStatus.OPENED,
            AdjustmentRequestStatus.RESPONDED,
            ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS,
        ),
        (
            InternalSignatureStatus.REQUESTING,
            InternalSignatureStatus.EDITING,
            ALLOWED_INTERNAL_SIGNATURE_TRANSITIONS,
        ),
        (
            InternalSignatureStatus.EDITING,
            InternalSignatureStatus.SIGNING,
            ALLOWED_INTERNAL_SIGNATURE_TRANSITIONS,
        ),
        (
            ModusignStatus.ON_GOING,
            ModusignStatus.COMPLETED,
            ALLOWED_MODUSIGN_TRANSITIONS,
        ),
        (
            ObligationStatus.SUBMITTED,
            ObligationStatus.APPROVED,
            ALLOWED_OBLIGATION_TRANSITIONS,
        ),
        (
            AnalysisStatus.PROCESSING,
            AnalysisStatus.COMPLETED,
            ALLOWED_ANALYSIS_TASK_TRANSITIONS,
        ),
    ],
)
def test_allows_domain_state_transitions(current, target, transitions) -> None:
    ensure_transition(current, target, transitions)


@pytest.mark.parametrize(
    ("current", "target", "transitions"),
    [
        (
            AdjustmentRequestStatus.RESPONDED,
            AdjustmentRequestStatus.OPENED,
            ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS,
        ),
        (
            InternalSignatureStatus.COMPLETED,
            InternalSignatureStatus.SIGNING,
            ALLOWED_INTERNAL_SIGNATURE_TRANSITIONS,
        ),
        (
            ModusignStatus.COMPLETED,
            ModusignStatus.ON_GOING,
            ALLOWED_MODUSIGN_TRANSITIONS,
        ),
        (
            ObligationStatus.PENDING,
            ObligationStatus.APPROVED,
            ALLOWED_OBLIGATION_TRANSITIONS,
        ),
        (
            AnalysisStatus.COMPLETED,
            AnalysisStatus.PROCESSING,
            ALLOWED_ANALYSIS_TASK_TRANSITIONS,
        ),
    ],
)
def test_rejects_domain_state_transitions(current, target, transitions) -> None:
    with pytest.raises(InvalidStatusTransition):
        ensure_transition(current, target, transitions)


async def test_state_machine_persists_contract_change_with_audit_event() -> None:
    repository = FakeStateTransitionRepository()
    service = StateMachineService(repository)
    contract_id = uuid4()

    changed = await service.transition_contract(
        contract_id=contract_id,
        current=ContractStatus.DRAFT,
        target=ContractStatus.ANALYZING,
        audit_event=_audit_event(),
    )

    assert changed is True
    assert len(repository.transitions) == 1
    transition = repository.transitions[0]
    assert transition.entity_id == contract_id
    assert transition.contract_id == contract_id
    assert transition.current_status is ContractStatus.DRAFT
    assert transition.target_status is ContractStatus.ANALYZING
    assert transition.audit_event.event_type is AuditEventType.ANALYSIS_STARTED


async def test_state_machine_does_not_persist_idempotent_replay() -> None:
    repository = FakeStateTransitionRepository()
    service = StateMachineService(repository)

    changed = await service.transition_contract(
        contract_id=uuid4(),
        current=ContractStatus.ANALYZING,
        target=ContractStatus.ANALYZING,
        audit_event=_audit_event(),
    )

    assert changed is False
    assert repository.transitions == []


async def test_state_machine_rejects_invalid_transition_before_persistence() -> None:
    repository = FakeStateTransitionRepository()
    service = StateMachineService(repository)

    with pytest.raises(InvalidStatusTransition):
        await service.transition_contract(
            contract_id=uuid4(),
            current=ContractStatus.DRAFT,
            target=ContractStatus.SIGNED,
            audit_event=_audit_event(),
        )

    assert repository.transitions == []


async def test_state_machine_rejects_concurrent_state_change() -> None:
    repository = FakeStateTransitionRepository(apply_transition=False)
    service = StateMachineService(repository)

    with pytest.raises(InvalidStatusTransition):
        await service.transition_contract(
            contract_id=uuid4(),
            current=ContractStatus.DRAFT,
            target=ContractStatus.ANALYZING,
            audit_event=_audit_event(),
        )

    assert len(repository.transitions) == 1


async def test_state_machine_rejects_an_audit_event_for_another_lifecycle() -> None:
    repository = FakeStateTransitionRepository()
    service = StateMachineService(repository)

    with pytest.raises(InvalidStatusTransition):
        await service.transition_adjustment_request(
            adjustment_request_id=uuid4(),
            contract_id=uuid4(),
            current=AdjustmentRequestStatus.DRAFT,
            target=AdjustmentRequestStatus.SENT,
            audit_event=_audit_event(),
        )

    assert repository.transitions == []


async def test_state_machine_completes_analysis_and_contract_together() -> None:
    repository = FakeStateTransitionRepository()
    service = StateMachineService(repository)
    contract_id = uuid4()
    task_id = uuid4()
    event = AuditEventInput(
        event_type=AuditEventType.ANALYSIS_COMPLETED,
        actor_type=AuditActorType.SYSTEM,
        summary="Analysis completed.",
    )

    changed = await service.complete_analysis(
        analysis_task_id=task_id,
        contract_id=contract_id,
        current_task=AnalysisStatus.PROCESSING,
        current_contract=ContractStatus.ANALYZING,
        audit_event=event,
    )

    assert changed is True
    assert repository.transitions == []
    assert repository.analysis_completions == [
        AnalysisCompletionTransition(
            analysis_task_id=task_id,
            contract_id=contract_id,
            current_task_status=AnalysisStatus.PROCESSING,
            current_contract_status=ContractStatus.ANALYZING,
            audit_event=event,
        )
    ]


async def test_invalid_status_transition_is_returned_as_a_safe_409_response() -> None:
    response = await invalid_status_transition_handler(
        Request({"type": "http", "method": "GET", "path": "/"}),
        InvalidStatusTransition("Invalid state transition."),
    )
    body = json.loads(response.body)

    assert response.status_code == 409
    assert body["data"] is None
    assert body["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert body["requestId"].startswith("req_")
