-- C-10: deterministic, owner-isolated P0 dashboard aggregation.

create or replace function public.get_owner_dashboard(
    p_owner_id uuid,
    p_today date
)
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
    with owned_contracts as (
        select
            contract.id,
            contract.status,
            contract.end_date,
            contract.termination_notice_date,
            contract.renewal_type,
            contract.total_amount
        from public.contracts contract
        where contract.owner_id = p_owner_id
    ),
    contract_counts as (
        select
            count(*) as total,
            count(*) filter (where status = 'SIGNING') as signing,
            count(*) filter (
                where status in ('IN_PROGRESS', 'RENEWAL_DUE')
            ) as in_progress,
            count(*) filter (where status = 'COMPLETED') as completed,
            count(*) filter (
                where (
                    end_date is not null
                    and end_date - p_today between 0 and 30
                )
                or (
                    termination_notice_date is not null
                    and termination_notice_date - p_today between 0 and 14
                )
                or (
                    renewal_type = 'AUTO'
                    and end_date is not null
                    and end_date - p_today between 0 and 7
                )
            ) as expiring_soon,
            coalesce(
                sum(total_amount) filter (
                    where status in (
                        'SIGNED',
                        'IN_PROGRESS',
                        'RENEWAL_DUE',
                        'COMPLETED'
                    )
                ),
                0
            ) as total_committed
        from owned_contracts
    ),
    unresolved_review_items as (
        select review.id, review.type
        from public.review_items review
        join owned_contracts contract on contract.id = review.contract_id
        where review.status in ('UNREVIEWED', 'SELECTED', 'SENT')
    ),
    signal_counts as (
        select
            review.type,
            count(*) as signal_count,
            case review.type
                when 'MISMATCH' then 1
                when 'NO_BASIS' then 2
                when 'UNCLEAR' then 3
                when 'MISSING' then 4
                when 'NEEDS_CHECK' then 5
                else 6
            end as tie_priority
        from unresolved_review_items review
        group by review.type
    ),
    requested_items as (
        select distinct item.review_item_id
        from public.adjustment_request_items item
        join public.adjustment_requests request
          on request.id = item.adjustment_request_id
        join owned_contracts contract
          on contract.id = request.contract_id
        join public.review_items review
          on review.id = item.review_item_id
         and review.contract_id = request.contract_id
        where request.status <> 'DRAFT'
    ),
    agreed_items as (
        select distinct clause.review_item_id
        from public.adjustment_final_clauses clause
        join public.adjustment_requests request
          on request.id = clause.adjustment_request_id
        join owned_contracts contract
          on contract.id = request.contract_id
        join public.review_items review
          on review.id = clause.review_item_id
         and review.contract_id = request.contract_id
        where clause.resolution in (
            'ACCEPT_REQUEST',
            'ACCEPT_COUNTERPROPOSAL'
        )
    ),
    rejected_items as (
        select response.review_item_id
        from public.adjustment_responses response
        join public.adjustment_requests request
          on request.id = response.adjustment_request_id
        join owned_contracts contract
          on contract.id = request.contract_id
        join public.review_items review
          on review.id = response.review_item_id
         and review.contract_id = request.contract_id
        where response.decision = 'REJECT'
        union
        select clause.review_item_id
        from public.adjustment_final_clauses clause
        join public.adjustment_requests request
          on request.id = clause.adjustment_request_id
        join owned_contracts contract
          on contract.id = request.contract_id
        join public.review_items review
          on review.id = clause.review_item_id
         and review.contract_id = request.contract_id
        where clause.resolution = 'KEEP_ORIGINAL'
    ),
    obligation_counts as (
        select
            count(*) filter (
                where obligation.status = 'PENDING'
            ) as obligation_pending,
            count(*) filter (
                where obligation.status = 'SUBMITTED'
            ) as obligation_submitted,
            count(*) filter (
                where obligation.status = 'APPROVED'
            ) as obligation_approved,
            coalesce(
                sum(contract.total_amount) filter (
                    where obligation.status = 'APPROVED'
                ),
                0
            ) as payment_condition_met_amount
        from public.obligations obligation
        join owned_contracts contract
          on contract.id = obligation.contract_id
    )
    select jsonb_build_object(
        'total', contract_counts.total,
        'signing', contract_counts.signing,
        'in_progress', contract_counts.in_progress,
        'completed', contract_counts.completed,
        'expiring_soon', contract_counts.expiring_soon,
        'unresolved_signals', (
            select count(*) from unresolved_review_items
        ),
        'adjustment_requested_clauses', (
            select count(*) from requested_items
        ),
        'adjustment_agreed_clauses', (
            select count(*) from agreed_items
        ),
        'adjustment_rejected_clauses', (
            select count(*) from rejected_items
        ),
        'obligation_pending', obligation_counts.obligation_pending,
        'obligation_submitted', obligation_counts.obligation_submitted,
        'obligation_approved', obligation_counts.obligation_approved,
        'total_committed', contract_counts.total_committed,
        'payment_condition_met_amount',
            obligation_counts.payment_condition_met_amount,
        'most_common_signal', (
            select signal.type
            from signal_counts signal
            order by signal.signal_count desc, signal.tie_priority, signal.type
            limit 1
        )
    )
    from contract_counts
    cross join obligation_counts;
$$;

revoke all on function public.get_owner_dashboard(uuid, date)
    from public, anon, authenticated;
grant execute on function public.get_owner_dashboard(uuid, date)
    to service_role;
