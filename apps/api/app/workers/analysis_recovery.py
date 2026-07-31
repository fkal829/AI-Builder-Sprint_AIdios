"""Run stale queued analysis recovery outside the HTTP request process."""

import argparse
import asyncio
import logging
from collections.abc import Sequence
from datetime import timedelta

from app.adapters.solar import SolarReviewAdapter
from app.adapters.supabase import SupabaseAdapter
from app.adapters.upstage import UpstageAdapter
from app.core.config import Settings, get_settings
from app.services.analysis import AnalysisService
from app.services.analysis_recovery import AnalysisRecoveryService

logger = logging.getLogger(__name__)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recover stale queued contract-analysis tasks.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one deterministic recovery scan and exit.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Keep scanning with ANALYSIS_RECOVERY_INTERVAL_SECONDS by default.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=None,
        help="Repeat scan interval in seconds; omitted runs once.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Maximum stale queued tasks per scan (1-100).",
    )
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=None,
        help="Only process tasks queued at least this many seconds (>=0).",
    )
    parser.add_argument(
        "--processing-timeout-seconds",
        type=int,
        default=None,
        help="Fail tasks left processing for at least this many seconds (>=60).",
    )
    args = parser.parse_args(argv)
    if args.once and (args.loop or args.interval_seconds is not None):
        parser.error("--once cannot be combined with --loop or --interval-seconds")
    if args.loop and args.interval_seconds is not None:
        parser.error("--loop uses the configured interval; omit --interval-seconds")
    if args.interval_seconds is not None and args.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")
    if args.batch_size is not None and not 1 <= args.batch_size <= 100:
        parser.error("--batch-size must be between 1 and 100")
    if args.stale_after_seconds is not None and args.stale_after_seconds < 0:
        parser.error("--stale-after-seconds must not be negative")
    if args.processing_timeout_seconds is not None and args.processing_timeout_seconds < 60:
        parser.error("--processing-timeout-seconds must be at least 60")
    return args


def build_service(settings: Settings) -> AnalysisRecoveryService:
    repository = SupabaseAdapter(
        mode=settings.supabase_mode,
        url=settings.supabase_url,
        service_role_key=settings.supabase_service_role_key,
        bucket=settings.supabase_storage_bucket,
        demo_owner_id=settings.demo_owner_id,
        demo_contract_id=settings.demo_contract_id,
        demo_bearer_token=settings.demo_bearer_token,
        mock_storage_access_base_url=settings.supabase_mock_storage_access_base_url,
    )
    processor = AnalysisService(
        adapter=UpstageAdapter(
            mode=settings.upstage_mode,
            api_key=settings.upstage_api_key,
            base_url=settings.upstage_base_url,
            parse_timeout_seconds=settings.upstage_parse_timeout_seconds,
            extract_timeout_seconds=settings.upstage_extract_timeout_seconds,
            extract_model=settings.upstage_extract_model,
        ),
        reviewer=SolarReviewAdapter(
            mode=settings.upstage_mode,
            api_key=settings.upstage_api_key,
            base_url=settings.upstage_base_url,
            timeout_seconds=settings.upstage_solar_timeout_seconds,
            model=settings.upstage_solar_model,
        ),
        contracts=repository,
        documents=repository,
        understood_terms=repository,
        analyses=repository,
        storage=repository,
    )
    return AnalysisRecoveryService(analyses=repository, processor=processor)


async def run_worker(args: argparse.Namespace, *, settings: Settings) -> None:
    service = build_service(settings)
    batch_size = args.batch_size or settings.analysis_recovery_batch_size
    stale_after_seconds = (
        args.stale_after_seconds
        if args.stale_after_seconds is not None
        else settings.analysis_recovery_stale_after_seconds
    )
    processing_timeout_seconds = (
        args.processing_timeout_seconds
        if args.processing_timeout_seconds is not None
        else settings.analysis_recovery_processing_timeout_seconds
    )
    interval_seconds = (
        args.interval_seconds
        if args.interval_seconds is not None
        else settings.analysis_recovery_interval_seconds
        if args.loop
        else None
    )

    while True:
        result = await service.run_once(
            stale_after=timedelta(seconds=stale_after_seconds),
            processing_timeout=timedelta(seconds=processing_timeout_seconds),
            batch_size=batch_size,
        )
        logger.info(
            "analysis_recovery_scan_complete candidates=%s dispatched=%s failed=%s timed_out=%s",
            result.candidates,
            result.dispatched,
            result.failed,
            result.timed_out,
        )
        if interval_seconds is None:
            return
        await asyncio.sleep(interval_seconds)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(run_worker(args, settings=get_settings()))


if __name__ == "__main__":
    main()
