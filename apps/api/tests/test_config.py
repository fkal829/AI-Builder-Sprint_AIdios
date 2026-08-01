import pytest

from app.core.config import Settings


def test_accepts_https_urls_and_bucket_limit_in_live_modes() -> None:
    settings = Settings(
        _env_file=None,
        supabase_mode="live",
        supabase_url="https://project.supabase.co",
        supabase_service_role_key="service-role-key",
        document_max_size_mib=20,
        upstage_mode="live",
        upstage_api_key="upstage-api-key",
        upstage_base_url="https://api.upstage.ai",
    )

    assert settings.document_max_size_mib == 20


@pytest.mark.parametrize(
    "supabase_url",
    [
        "http://project.supabase.co",
        "https://",
        "not-a-url",
    ],
)
def test_rejects_non_https_supabase_url_in_live_mode(supabase_url: str) -> None:
    with pytest.raises(ValueError, match="SUPABASE_URL.*HTTPS"):
        Settings(
            _env_file=None,
            supabase_mode="live",
            supabase_url=supabase_url,
            supabase_service_role_key="service-role-key",
        )


@pytest.mark.parametrize(
    "upstage_base_url",
    [
        "http://api.upstage.ai",
        "https://",
        "not-a-url",
    ],
)
def test_rejects_non_https_upstage_base_url_in_live_mode(
    upstage_base_url: str,
) -> None:
    with pytest.raises(ValueError, match="UPSTAGE_BASE_URL.*HTTPS"):
        Settings(
            _env_file=None,
            upstage_mode="live",
            upstage_api_key="upstage-api-key",
            upstage_base_url=upstage_base_url,
        )


def test_rejects_document_size_above_bucket_limit_in_live_supabase_mode() -> None:
    with pytest.raises(ValueError, match="DOCUMENT_MAX_SIZE_MIB.*20MiB"):
        Settings(
            _env_file=None,
            supabase_mode="live",
            supabase_url="https://project.supabase.co",
            supabase_service_role_key="service-role-key",
            document_max_size_mib=21,
        )


def test_allows_larger_document_size_in_mock_supabase_mode() -> None:
    settings = Settings(
        _env_file=None,
        supabase_mode="mock",
        document_max_size_mib=100,
    )

    assert settings.document_max_size_mib == 100
