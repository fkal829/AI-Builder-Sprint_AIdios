from dataclasses import dataclass
from uuid import uuid4

from app.core.enums import (
    AnalysisStatus,
    AuditActorType,
    AuditEventType,
    ContractStatus,
    StateEntityType,
)
from app.repositories.state_transitions import SupabaseStateTransitionRepository
from app.services.state_machine import (
    AnalysisCompletionTransition,
    AuditEventInput,
    StateTransition,
)


@dataclass
class FakeRpcResponse:
    data: bool


class FakeRpcRequest:
    def __init__(self, response: FakeRpcResponse) -> None:
        self._response = response

    async def execute(self) -> FakeRpcResponse:
        return self._response


class FakeSupabaseClient:
    def __init__(self, *, result: bool) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, object]]] = []

    def rpc(self, function_name: str, params: dict[str, object]) -> FakeRpcRequest:
        self.calls.append((function_name, params))
        return FakeRpcRequest(FakeRpcResponse(self.result))


async def test_repository_calls_atomic_state_transition_rpc() -> None:
    client = FakeSupabaseClient(result=True)
    repository = SupabaseStateTransitionRepository(client)
    contract_id = uuid4()
    transition = StateTransition(
        entity_type=StateEntityType.CONTRACT,
        entity_id=contract_id,
        contract_id=contract_id,
        current_status=ContractStatus.DRAFT,
        target_status=ContractStatus.ANALYZING,
        audit_event=AuditEventInput(
            event_type=AuditEventType.ANALYSIS_STARTED,
            actor_type=AuditActorType.OWNER,
            summary="Analysis started.",
        ),
    )

    changed = await repository.transition_with_audit(transition=transition)

    assert changed is True
    assert client.calls == [
        (
            "apply_state_transition_with_audit",
            {
                "p_entity_type": "CONTRACT",
                "p_entity_id": str(contract_id),
                "p_contract_id": str(contract_id),
                "p_current_status": "DRAFT",
                "p_target_status": "ANALYZING",
                "p_event_type": "ANALYSIS_STARTED",
                "p_actor_type": "OWNER",
                "p_summary": "Analysis started.",
            },
        )
    ]


async def test_repository_returns_false_when_compare_and_set_does_not_match() -> None:
    client = FakeSupabaseClient(result=False)
    repository = SupabaseStateTransitionRepository(client)
    contract_id = uuid4()
    transition = StateTransition(
        entity_type=StateEntityType.CONTRACT,
        entity_id=contract_id,
        contract_id=contract_id,
        current_status=ContractStatus.DRAFT,
        target_status=ContractStatus.ANALYZING,
        audit_event=AuditEventInput(
            event_type=AuditEventType.ANALYSIS_STARTED,
            actor_type=AuditActorType.OWNER,
        ),
    )

    assert await repository.transition_with_audit(transition=transition) is False


async def test_repository_calls_atomic_analysis_completion_rpc() -> None:
    client = FakeSupabaseClient(result=True)
    repository = SupabaseStateTransitionRepository(client)
    contract_id = uuid4()
    task_id = uuid4()

    changed = await repository.complete_analysis_with_audit(
        transition=AnalysisCompletionTransition(
            analysis_task_id=task_id,
            contract_id=contract_id,
            current_task_status=AnalysisStatus.PROCESSING,
            current_contract_status=ContractStatus.ANALYZING,
            audit_event=AuditEventInput(
                event_type=AuditEventType.ANALYSIS_COMPLETED,
                actor_type=AuditActorType.SYSTEM,
                summary="Analysis completed.",
            ),
        )
    )

    assert changed is True
    assert client.calls == [
        (
            "complete_analysis_with_audit",
            {
                "p_analysis_task_id": str(task_id),
                "p_contract_id": str(contract_id),
                "p_current_task_status": "PROCESSING",
                "p_current_contract_status": "ANALYZING",
                "p_event_type": "ANALYSIS_COMPLETED",
                "p_actor_type": "SYSTEM",
                "p_summary": "Analysis completed.",
            },
        )
    ]
