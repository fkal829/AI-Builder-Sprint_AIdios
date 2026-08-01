from app.core.errors import ErrorCode


class ApiException(Exception):
    def __init__(self, *, status_code: int, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class UnauthorizedAccess(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=401,
            code=ErrorCode.UNAUTHORIZED_ACCESS,
            message="인증이 필요합니다.",
        )


class ResourceNotFound(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="요청한 리소스를 찾을 수 없습니다.",
        )


class InvalidDocument(ApiException):
    def __init__(self, message: str) -> None:
        super().__init__(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message=message,
        )


class InvalidAdjustmentRequest(ApiException):
    def __init__(self, message: str) -> None:
        super().__init__(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message=message,
        )


class IdempotencyConflict(ApiException):
    def __init__(
        self,
        message: str = "같은 멱등 키에 다른 요청을 사용할 수 없습니다.",
    ) -> None:
        super().__init__(
            status_code=409,
            code=ErrorCode.IDEMPOTENCY_CONFLICT,
            message=message,
        )


class PerformanceReportPeriodAlreadyExists(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code=ErrorCode.REPORT_PERIOD_ALREADY_EXISTS,
            message="해당 계약과 월의 광고효과 리포트가 이미 존재합니다.",
        )


class PerformanceReportExtractionInProgress(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code=ErrorCode.REPORT_EXTRACTION_IN_PROGRESS,
            message="광고효과 리포트를 추출하고 있습니다. 완료 후 다시 확인해 주세요.",
        )


class PerformanceReportExtractFailed(ApiException):
    def __init__(self, *, request_id: str | None = None) -> None:
        self.request_id = request_id
        super().__init__(
            status_code=502,
            code=ErrorCode.REPORT_EXTRACT_FAILED,
            message=(
                "광고효과 리포트에서 지표를 추출하지 못했습니다. 새 요청으로 다시 시도해 주세요."
            ),
        )


class PerformanceReportRevisionConflict(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code=ErrorCode.REPORT_REVISION_CONFLICT,
            message="다른 요청이 먼저 이 리포트를 확정·정정했습니다. 최신 값을 다시 확인해 주세요.",
        )


class PerformanceReportPeriodOrderConflict(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code=ErrorCode.REPORT_PERIOD_ORDER_CONFLICT,
            message=(
                "더 뒤 월의 리포트가 이미 확정되어 이 월을 처음 확정할 수 없습니다. "
                "월 순서대로 다시 확인해 주세요."
            ),
        )


class PerformanceReportCorrectionDependencyExists(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code=ErrorCode.REPORT_CORRECTION_DEPENDENCY_EXISTS,
            message="더 뒤 월의 확정된 리포트가 있어 이 리포트는 정정할 수 없습니다.",
        )


class AnalysisStartUnavailable(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code=ErrorCode.ANALYSIS_START_FAILED,
            message="분석 작업을 접수하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        )


class ExternalServiceUnavailable(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code=ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE,
            message="요청한 서비스를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        )


class CounterproposalComparisonUnavailable(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=502,
            code=ErrorCode.ANALYSIS_SCHEMA_INVALID,
            message="역제안 비교를 완료하지 못했습니다. 잠시 후 다시 확인해 주세요.",
        )


class TonePolishUnavailable(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=502,
            code=ErrorCode.ANALYSIS_SCHEMA_INVALID,
            message="문구를 안전하게 다듬지 못했습니다. 원문을 확인한 뒤 다시 시도해 주세요.",
        )


class ModusignRequestFailed(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=502,
            code=ErrorCode.MODUSIGN_REQUEST_FAILED,
            message="Unable to create the signature request.",
        )


class WebhookAuthenticationFailed(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=401,
            code=ErrorCode.WEBHOOK_AUTH_FAILED,
            message="웹훅 인증에 실패했습니다.",
        )


class PublicTokenExpired(ApiException):
    def __init__(self, *, code: ErrorCode) -> None:
        super().__init__(
            status_code=410,
            code=code,
            message="공개 링크가 만료되었습니다.",
        )


class ExternalStorageFailure(RuntimeError):
    """Private storage or metadata persistence failed without exposing vendor details."""
