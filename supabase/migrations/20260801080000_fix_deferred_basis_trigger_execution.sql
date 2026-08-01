-- P2 16.4 deployment fix: deferred constraint triggers fire at transaction
-- commit, after the SECURITY DEFINER confirmation RPC has returned to the
-- service_role session. Run only the closed, fully-qualified trigger wrapper as
-- its owner so it can call the non-public assertion helper at commit time.
alter function public.enforce_performance_flag_basis_completeness()
    security definer;

revoke all on function public.enforce_performance_flag_basis_completeness()
    from public, anon, authenticated, service_role;

