from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.core.enums import (
    AdjustmentRequestStatus,
    AnalysisStatus,
    AuditActorType,
    AuditEventType,
    ContractStatus,
    InternalSignatureStatus,
    ModusignStatus,
    ObligationStatus,
    StateEntityType,
)
from app.core.errors import ErrorCode

ALLOWED_CONTRACT_TRANSITIONS: dict[ContractStatus, set[ContractStatus]] = {
    ContractStatus.DRAFT: {ContractStatus.ANALYZING},
    ContractStatus.ANALYZING: {ContractStatus.REVIEW_REQUIRED},
    ContractStatus.REVIEW_REQUIRED: {
        ContractStatus.NEGOTIATING,
        ContractStatus.READY_TO_SIGN,
    },
    ContractStatus.NEGOTIATING: {ContractStatus.READY_TO_SIGN},
    # A terminal document status can be observed before its ON_GOING webhook.
    # Reconciliation may therefore atomically catch READY_TO_SIGN up to SIGNED.
    ContractStatus.READY_TO_SIGN: {ContractStatus.SIGNING, ContractStatus.SIGNED},
    ContractStatus.SIGNING: {ContractStatus.SIGNED, ContractStatus.READY_TO_SIGN},
    ContractStatus.SIGNED: {ContractStatus.IN_PROGRESS},
    ContractStatus.IN_PROGRESS: {
        ContractStatus.COMPLETED,
        ContractStatus.RENEWAL_DUE,
    },
    ContractStatus.COMPLETED: set(),
    ContractStatus.RENEWAL_DUE: set(),
}

ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS: dict[
    AdjustmentRequestStatus, set[AdjustmentRequestStatus]
] = {
    AdjustmentRequestStatus.DRAFT: {AdjustmentRequestStatus.SENT},
    AdjustmentRequestStatus.SENT: {
        AdjustmentRequestStatus.OPENED,
        AdjustmentRequestStatus.RESPONDED,
        AdjustmentRequestStatus.EXPIRED,
    },
    AdjustmentRequestStatus.OPENED: {
        AdjustmentRequestStatus.RESPONDED,
        AdjustmentRequestStatus.EXPIRED,
    },
    AdjustmentRequestStatus.RESPONDED: {AdjustmentRequestStatus.CONFIRMED},
    AdjustmentRequestStatus.CONFIRMED: set(),
    AdjustmentRequestStatus.EXPIRED: set(),
}

ALLOWED_MODUSIGN_TRANSITIONS: dict[ModusignStatus, set[ModusignStatus]] = {
    ModusignStatus.DRAFT: {ModusignStatus.SCHEDULED, ModusignStatus.ON_PROCESSING},
    ModusignStatus.SCHEDULED: {
        ModusignStatus.ON_PROCESSING,
        ModusignStatus.ABORTED,
        ModusignStatus.PROCESSING_FAILED,
    },
    ModusignStatus.ON_PROCESSING: {
        ModusignStatus.ON_GOING,
        ModusignStatus.ABORTED,
        ModusignStatus.PROCESSING_FAILED,
    },
    ModusignStatus.ON_GOING: {
        ModusignStatus.COMPLETED,
        ModusignStatus.ABORTED,
        ModusignStatus.PROCESSING_FAILED,
    },
    ModusignStatus.COMPLETED: set(),
    ModusignStatus.ABORTED: set(),
    ModusignStatus.PROCESSING_FAILED: set(),
}

ALLOWED_INTERNAL_SIGNATURE_TRANSITIONS: dict[
    InternalSignatureStatus, set[InternalSignatureStatus]
] = {
    InternalSignatureStatus.REQUEST_READY: {InternalSignatureStatus.REQUESTING},
    InternalSignatureStatus.REQUESTING: {
        InternalSignatureStatus.EDITING,
        InternalSignatureStatus.FAILED,
    },
    InternalSignatureStatus.EDITING: {
        InternalSignatureStatus.SIGNING,
        InternalSignatureStatus.COMPLETED,
        InternalSignatureStatus.ABORTED,
        InternalSignatureStatus.FAILED,
    },
    InternalSignatureStatus.SIGNING: {
        InternalSignatureStatus.COMPLETED,
        InternalSignatureStatus.ABORTED,
        InternalSignatureStatus.FAILED,
    },
    InternalSignatureStatus.COMPLETED: set(),
    InternalSignatureStatus.ABORTED: set(),
    InternalSignatureStatus.FAILED: set(),
}

ALLOWED_OBLIGATION_TRANSITIONS: dict[ObligationStatus, set[ObligationStatus]] = {
    ObligationStatus.PENDING: {ObligationStatus.SUBMITTED},
    ObligationStatus.SUBMITTED: {
        ObligationStatus.APPROVED,
        ObligationStatus.DISPUTED,
    },
    ObligationStatus.APPROVED: set(),
    ObligationStatus.DISPUTED: set(),
}

ALLOWED_ANALYSIS_TASK_TRANSITIONS: dict[AnalysisStatus, set[AnalysisStatus]] = {
    AnalysisStatus.QUEUED: {AnalysisStatus.PROCESSING},
    AnalysisStatus.PROCESSING: {AnalysisStatus.COMPLETED, AnalysisStatus.FAILED},
    AnalysisStatus.COMPLETED: set(),
    AnalysisStatus.FAILED: set(),
}


class InvalidStatusTransition(ValueError):
    code = ErrorCode.INVALID_STATUS_TRANSITION


@dataclass(frozen=True)
class AuditEventInput:
    """Safe audit fields recorded with a state change.

    Contract text, contact information, public tokens, and signing URLs must never
    be included in ``summary``.
    """

    event_type: AuditEventType
    actor_type: AuditActorType
    summary: str | None = None


@dataclass(frozen=True)
class AuditRule:
    """The only audit event/actor combinations allowed for a state edge."""

    event_types: frozenset[AuditEventType]
    actor_types: frozenset[AuditActorType]


OBLIGATION_ENTITY = StateEntityType.OBLIGATION
ANALYSIS_TASK_ENTITY = StateEntityType.ANALYSIS_TASK


def _audit_rule(
    *event_types: AuditEventType,
    actors: tuple[AuditActorType, ...],
) -> AuditRule:
    return AuditRule(frozenset(event_types), frozenset(actors))


# An audit entry must describe the lifecycle change it accompanies.  Keeping the
# mapping beside the state graphs prevents a caller from recording, for example,
# ANALYSIS_STARTED while changing a signature state.
AUDIT_RULES: dict[tuple[StateEntityType, StrEnum, StrEnum], AuditRule] = {
    (StateEntityType.CONTRACT, ContractStatus.DRAFT, ContractStatus.ANALYZING): _audit_rule(
        AuditEventType.ANALYSIS_STARTED, actors=(AuditActorType.OWNER,)
    ),
    (
        StateEntityType.CONTRACT,
        ContractStatus.ANALYZING,
        ContractStatus.REVIEW_REQUIRED,
    ): _audit_rule(AuditEventType.ANALYSIS_COMPLETED, actors=(AuditActorType.SYSTEM,)),
    (
        StateEntityType.CONTRACT,
        ContractStatus.REVIEW_REQUIRED,
        ContractStatus.NEGOTIATING,
    ): _audit_rule(AuditEventType.ADJUSTMENT_SENT, actors=(AuditActorType.OWNER,)),
    (
        StateEntityType.CONTRACT,
        ContractStatus.REVIEW_REQUIRED,
        ContractStatus.READY_TO_SIGN,
    ): _audit_rule(AuditEventType.AGREEMENT_CREATED, actors=(AuditActorType.OWNER,)),
    (
        StateEntityType.CONTRACT,
        ContractStatus.NEGOTIATING,
        ContractStatus.READY_TO_SIGN,
    ): _audit_rule(AuditEventType.ADJUSTMENT_CONFIRMED, actors=(AuditActorType.OWNER,)),
    (
        StateEntityType.CONTRACT,
        ContractStatus.READY_TO_SIGN,
        ContractStatus.SIGNING,
    ): _audit_rule(AuditEventType.SIGNATURE_REQUESTED, actors=(AuditActorType.OWNER,)),
    (StateEntityType.CONTRACT, ContractStatus.SIGNING, ContractStatus.SIGNED): _audit_rule(
        AuditEventType.SIGNATURE_COMPLETED, actors=(AuditActorType.SYSTEM,)
    ),
    (StateEntityType.CONTRACT, ContractStatus.READY_TO_SIGN, ContractStatus.SIGNED): _audit_rule(
        AuditEventType.SIGNATURE_COMPLETED, actors=(AuditActorType.SYSTEM,)
    ),
    (
        StateEntityType.CONTRACT,
        ContractStatus.SIGNING,
        ContractStatus.READY_TO_SIGN,
    ): _audit_rule(
        AuditEventType.SIGNATURE_ABORTED,
        AuditEventType.SIGNATURE_FAILED,
        actors=(AuditActorType.SYSTEM,),
    ),
    (StateEntityType.CONTRACT, ContractStatus.SIGNED, ContractStatus.IN_PROGRESS): _audit_rule(
        AuditEventType.CONTRACT_STARTED, actors=(AuditActorType.SYSTEM,)
    ),
    (StateEntityType.CONTRACT, ContractStatus.IN_PROGRESS, ContractStatus.COMPLETED): _audit_rule(
        AuditEventType.CONTRACT_COMPLETED, actors=(AuditActorType.SYSTEM,)
    ),
    (StateEntityType.CONTRACT, ContractStatus.IN_PROGRESS, ContractStatus.RENEWAL_DUE): _audit_rule(
        AuditEventType.CONTRACT_RENEWAL_DUE, actors=(AuditActorType.SYSTEM,)
    ),
    (
        StateEntityType.ADJUSTMENT_REQUEST,
        AdjustmentRequestStatus.DRAFT,
        AdjustmentRequestStatus.SENT,
    ): _audit_rule(AuditEventType.ADJUSTMENT_SENT, actors=(AuditActorType.OWNER,)),
    (
        StateEntityType.ADJUSTMENT_REQUEST,
        AdjustmentRequestStatus.SENT,
        AdjustmentRequestStatus.OPENED,
    ): _audit_rule(AuditEventType.ADJUSTMENT_OPENED, actors=(AuditActorType.AGENCY,)),
    (
        StateEntityType.ADJUSTMENT_REQUEST,
        AdjustmentRequestStatus.SENT,
        AdjustmentRequestStatus.RESPONDED,
    ): _audit_rule(AuditEventType.ADJUSTMENT_RESPONDED, actors=(AuditActorType.AGENCY,)),
    (
        StateEntityType.ADJUSTMENT_REQUEST,
        AdjustmentRequestStatus.OPENED,
        AdjustmentRequestStatus.RESPONDED,
    ): _audit_rule(AuditEventType.ADJUSTMENT_RESPONDED, actors=(AuditActorType.AGENCY,)),
    (
        StateEntityType.ADJUSTMENT_REQUEST,
        AdjustmentRequestStatus.SENT,
        AdjustmentRequestStatus.EXPIRED,
    ): _audit_rule(AuditEventType.ADJUSTMENT_EXPIRED, actors=(AuditActorType.SYSTEM,)),
    (
        StateEntityType.ADJUSTMENT_REQUEST,
        AdjustmentRequestStatus.OPENED,
        AdjustmentRequestStatus.EXPIRED,
    ): _audit_rule(AuditEventType.ADJUSTMENT_EXPIRED, actors=(AuditActorType.SYSTEM,)),
    (
        StateEntityType.ADJUSTMENT_REQUEST,
        AdjustmentRequestStatus.RESPONDED,
        AdjustmentRequestStatus.CONFIRMED,
    ): _audit_rule(AuditEventType.ADJUSTMENT_CONFIRMED, actors=(AuditActorType.OWNER,)),
    (
        StateEntityType.INTERNAL_SIGNATURE,
        InternalSignatureStatus.REQUEST_READY,
        InternalSignatureStatus.REQUESTING,
    ): _audit_rule(AuditEventType.SIGNATURE_DRAFT_CREATED, actors=(AuditActorType.OWNER,)),
    (
        StateEntityType.INTERNAL_SIGNATURE,
        InternalSignatureStatus.REQUESTING,
        InternalSignatureStatus.EDITING,
    ): _audit_rule(AuditEventType.SIGNATURE_DRAFT_CREATED, actors=(AuditActorType.OWNER,)),
    (
        StateEntityType.INTERNAL_SIGNATURE,
        InternalSignatureStatus.EDITING,
        InternalSignatureStatus.SIGNING,
    ): _audit_rule(AuditEventType.SIGNATURE_STARTED, actors=(AuditActorType.SYSTEM,)),
    (
        StateEntityType.INTERNAL_SIGNATURE,
        InternalSignatureStatus.SIGNING,
        InternalSignatureStatus.COMPLETED,
    ): _audit_rule(AuditEventType.SIGNATURE_COMPLETED, actors=(AuditActorType.SYSTEM,)),
    (
        StateEntityType.INTERNAL_SIGNATURE,
        InternalSignatureStatus.EDITING,
        InternalSignatureStatus.ABORTED,
    ): _audit_rule(AuditEventType.SIGNATURE_ABORTED, actors=(AuditActorType.SYSTEM,)),
    (
        StateEntityType.INTERNAL_SIGNATURE,
        InternalSignatureStatus.SIGNING,
        InternalSignatureStatus.ABORTED,
    ): _audit_rule(AuditEventType.SIGNATURE_ABORTED, actors=(AuditActorType.SYSTEM,)),
    (
        StateEntityType.INTERNAL_SIGNATURE,
        InternalSignatureStatus.REQUESTING,
        InternalSignatureStatus.FAILED,
    ): _audit_rule(AuditEventType.SIGNATURE_FAILED, actors=(AuditActorType.SYSTEM,)),
    (
        StateEntityType.INTERNAL_SIGNATURE,
        InternalSignatureStatus.EDITING,
        InternalSignatureStatus.FAILED,
    ): _audit_rule(AuditEventType.SIGNATURE_FAILED, actors=(AuditActorType.SYSTEM,)),
    (
        StateEntityType.INTERNAL_SIGNATURE,
        InternalSignatureStatus.SIGNING,
        InternalSignatureStatus.FAILED,
    ): _audit_rule(AuditEventType.SIGNATURE_FAILED, actors=(AuditActorType.SYSTEM,)),
    (OBLIGATION_ENTITY, ObligationStatus.PENDING, ObligationStatus.SUBMITTED): _audit_rule(
        AuditEventType.EVIDENCE_SUBMITTED, actors=(AuditActorType.AGENCY,)
    ),
    (
        StateEntityType.INTERNAL_SIGNATURE,
        InternalSignatureStatus.EDITING,
        InternalSignatureStatus.COMPLETED,
    ): _audit_rule(AuditEventType.SIGNATURE_COMPLETED, actors=(AuditActorType.SYSTEM,)),
    (
        OBLIGATION_ENTITY,
        ObligationStatus.SUBMITTED,
        ObligationStatus.APPROVED,
    ): _audit_rule(AuditEventType.EVIDENCE_APPROVED, actors=(AuditActorType.OWNER,)),
    (
        OBLIGATION_ENTITY,
        ObligationStatus.SUBMITTED,
        ObligationStatus.DISPUTED,
    ): _audit_rule(AuditEventType.EVIDENCE_DISPUTED, actors=(AuditActorType.OWNER,)),
    (ANALYSIS_TASK_ENTITY, AnalysisStatus.QUEUED, AnalysisStatus.PROCESSING): _audit_rule(
        AuditEventType.ANALYSIS_STARTED, actors=(AuditActorType.SYSTEM,)
    ),
    (
        ANALYSIS_TASK_ENTITY,
        AnalysisStatus.PROCESSING,
        AnalysisStatus.COMPLETED,
    ): _audit_rule(AuditEventType.ANALYSIS_COMPLETED, actors=(AuditActorType.SYSTEM,)),
    (ANALYSIS_TASK_ENTITY, AnalysisStatus.PROCESSING, AnalysisStatus.FAILED): _audit_rule(
        AuditEventType.ANALYSIS_FAILED, actors=(AuditActorType.SYSTEM,)
    ),
}


@dataclass(frozen=True)
class StateTransition:
    """A compare-and-set status change tied to one contract audit event."""

    entity_type: StateEntityType
    entity_id: UUID
    contract_id: UUID
    current_status: StrEnum
    target_status: StrEnum
    audit_event: AuditEventInput


@dataclass(frozen=True)
class AnalysisCompletionTransition:
    """The analysis success path changes task and contract state atomically."""

    analysis_task_id: UUID
    contract_id: UUID
    current_task_status: AnalysisStatus
    current_contract_status: ContractStatus
    audit_event: AuditEventInput


class StateTransitionRepository(Protocol):
    """Persistence boundary for state transitions.

    Implementations must update the entity only when ``current_status`` still
    matches and append the audit event in the same database transaction. Return
    ``False`` when the compare-and-set update affects no row.
    """

    async def transition_with_audit(self, *, transition: StateTransition) -> bool: ...

    async def complete_analysis_with_audit(
        self,
        *,
        transition: AnalysisCompletionTransition,
    ) -> bool: ...


class StateMachineService:
    """Validates lifecycle changes before their atomic persistence."""

    def __init__(self, repository: StateTransitionRepository) -> None:
        self._repository = repository

    async def transition_contract(
        self,
        *,
        contract_id: UUID,
        current: ContractStatus,
        target: ContractStatus,
        audit_event: AuditEventInput,
    ) -> bool:
        return await self._transition(
            entity_type=StateEntityType.CONTRACT,
            entity_id=contract_id,
            contract_id=contract_id,
            current=current,
            target=target,
            transitions=ALLOWED_CONTRACT_TRANSITIONS,
            audit_event=audit_event,
        )

    async def transition_adjustment_request(
        self,
        *,
        adjustment_request_id: UUID,
        contract_id: UUID,
        current: AdjustmentRequestStatus,
        target: AdjustmentRequestStatus,
        audit_event: AuditEventInput,
    ) -> bool:
        return await self._transition(
            entity_type=StateEntityType.ADJUSTMENT_REQUEST,
            entity_id=adjustment_request_id,
            contract_id=contract_id,
            current=current,
            target=target,
            transitions=ALLOWED_ADJUSTMENT_REQUEST_TRANSITIONS,
            audit_event=audit_event,
        )

    async def transition_signature(
        self,
        *,
        signature_id: UUID,
        contract_id: UUID,
        current: InternalSignatureStatus,
        target: InternalSignatureStatus,
        audit_event: AuditEventInput,
    ) -> bool:
        return await self._transition(
            entity_type=StateEntityType.INTERNAL_SIGNATURE,
            entity_id=signature_id,
            contract_id=contract_id,
            current=current,
            target=target,
            transitions=ALLOWED_INTERNAL_SIGNATURE_TRANSITIONS,
            audit_event=audit_event,
        )

    async def transition_obligation(
        self,
        *,
        obligation_id: UUID,
        contract_id: UUID,
        current: ObligationStatus,
        target: ObligationStatus,
        audit_event: AuditEventInput,
    ) -> bool:
        return await self._transition(
            entity_type=StateEntityType.OBLIGATION,
            entity_id=obligation_id,
            contract_id=contract_id,
            current=current,
            target=target,
            transitions=ALLOWED_OBLIGATION_TRANSITIONS,
            audit_event=audit_event,
        )

    async def transition_analysis_task(
        self,
        *,
        analysis_task_id: UUID,
        contract_id: UUID,
        current: AnalysisStatus,
        target: AnalysisStatus,
        audit_event: AuditEventInput,
    ) -> bool:
        return await self._transition(
            entity_type=StateEntityType.ANALYSIS_TASK,
            entity_id=analysis_task_id,
            contract_id=contract_id,
            current=current,
            target=target,
            transitions=ALLOWED_ANALYSIS_TASK_TRANSITIONS,
            audit_event=audit_event,
        )

    async def complete_analysis(
        self,
        *,
        analysis_task_id: UUID,
        contract_id: UUID,
        current_task: AnalysisStatus,
        current_contract: ContractStatus,
        audit_event: AuditEventInput,
    ) -> bool:
        """Record a successful B analysis without leaving task/contract out of sync."""

        ensure_transition(
            current_task,
            AnalysisStatus.COMPLETED,
            ALLOWED_ANALYSIS_TASK_TRANSITIONS,
        )
        ensure_transition(
            current_contract,
            ContractStatus.REVIEW_REQUIRED,
            ALLOWED_CONTRACT_TRANSITIONS,
        )
        ensure_audit_rule(
            StateEntityType.ANALYSIS_TASK,
            current_task,
            AnalysisStatus.COMPLETED,
            audit_event,
        )
        ensure_audit_rule(
            StateEntityType.CONTRACT,
            current_contract,
            ContractStatus.REVIEW_REQUIRED,
            audit_event,
        )
        transition = AnalysisCompletionTransition(
            analysis_task_id=analysis_task_id,
            contract_id=contract_id,
            current_task_status=current_task,
            current_contract_status=current_contract,
            audit_event=audit_event,
        )
        if not await self._repository.complete_analysis_with_audit(transition=transition):
            raise InvalidStatusTransition("The analysis or contract state has already changed.")
        return True

    async def _transition[StatusT: StrEnum](
        self,
        *,
        entity_type: StateEntityType,
        entity_id: UUID,
        contract_id: UUID,
        current: StatusT,
        target: StatusT,
        transitions: Mapping[StatusT, set[StatusT]],
        audit_event: AuditEventInput,
    ) -> bool:
        if current == target:
            return False

        ensure_transition(current, target, transitions)
        ensure_audit_rule(entity_type, current, target, audit_event)
        transition = StateTransition(
            entity_type=entity_type,
            entity_id=entity_id,
            contract_id=contract_id,
            current_status=current,
            target_status=target,
            audit_event=audit_event,
        )
        if not await self._repository.transition_with_audit(transition=transition):
            raise InvalidStatusTransition("상태가 이미 변경되어 요청을 처리할 수 없습니다.")
        return True


def ensure_contract_transition(
    current: ContractStatus,
    target: ContractStatus,
) -> None:
    if target not in ALLOWED_CONTRACT_TRANSITIONS[current]:
        message = f"{current}에서 {target}(으)로 변경할 수 없습니다."
        raise InvalidStatusTransition(message)


def ensure_audit_rule(
    entity_type: StateEntityType,
    current: StrEnum,
    target: StrEnum,
    audit_event: AuditEventInput,
) -> None:
    rule = AUDIT_RULES.get((entity_type, current, target))
    if rule is None:
        raise InvalidStatusTransition("No audit rule is defined for this state transition.")
    if audit_event.event_type not in rule.event_types:
        raise InvalidStatusTransition("The audit event does not match this state transition.")
    if audit_event.actor_type not in rule.actor_types:
        raise InvalidStatusTransition("The actor cannot perform this state transition.")


def ensure_transition[StatusT: StrEnum](
    current: StatusT,
    target: StatusT,
    transitions: Mapping[StatusT, set[StatusT]],
) -> None:
    if target not in transitions[current]:
        message = f"{current}에서 {target}(으)로 변경할 수 없습니다."
        raise InvalidStatusTransition(message)
