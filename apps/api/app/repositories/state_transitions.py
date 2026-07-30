"""Supabase implementation of the state-transition persistence boundary."""

from typing import Any, Protocol

from app.services.state_machine import AnalysisCompletionTransition, StateTransition


class RpcRequest(Protocol):
    async def execute(self) -> Any: ...


class SupabaseRpcClient(Protocol):
    def rpc(self, function_name: str, params: dict[str, Any]) -> RpcRequest: ...


class SupabaseStateTransitionRepository:
    """Persists a compare-and-set update and its audit event through one RPC.

    PostgreSQL executes a function invocation in one transaction, so the status
    update and audit insert cannot be committed independently.
    """

    def __init__(self, client: SupabaseRpcClient) -> None:
        self._client = client

    async def transition_with_audit(self, *, transition: StateTransition) -> bool:
        response = await self._client.rpc(
            "apply_state_transition_with_audit",
            {
                "p_entity_type": transition.entity_type.value,
                "p_entity_id": str(transition.entity_id),
                "p_contract_id": str(transition.contract_id),
                "p_current_status": transition.current_status.value,
                "p_target_status": transition.target_status.value,
                "p_event_type": transition.audit_event.event_type.value,
                "p_actor_type": transition.audit_event.actor_type.value,
                "p_summary": transition.audit_event.summary,
            },
        ).execute()
        if not isinstance(response.data, bool):
            raise RuntimeError("State transition RPC returned an invalid response.")
        return response.data

    async def complete_analysis_with_audit(
        self,
        *,
        transition: AnalysisCompletionTransition,
    ) -> bool:
        response = await self._client.rpc(
            "complete_analysis_with_audit",
            {
                "p_analysis_task_id": str(transition.analysis_task_id),
                "p_contract_id": str(transition.contract_id),
                "p_current_task_status": transition.current_task_status.value,
                "p_current_contract_status": transition.current_contract_status.value,
                "p_event_type": transition.audit_event.event_type.value,
                "p_actor_type": transition.audit_event.actor_type.value,
                "p_summary": transition.audit_event.summary,
            },
        ).execute()
        if not isinstance(response.data, bool):
            raise RuntimeError("Analysis completion RPC returned an invalid response.")
        return response.data
