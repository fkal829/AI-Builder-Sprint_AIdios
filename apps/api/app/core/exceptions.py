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
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code=ErrorCode.IDEMPOTENCY_CONFLICT,
            message="같은 멱등 키에 다른 요청을 사용할 수 없습니다.",
        )


class AnalysisStartUnavailable(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code=ErrorCode.ANALYSIS_START_FAILED,
            message="분석 작업을 접수하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        )


class CounterproposalComparisonUnavailable(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=502,
            code=ErrorCode.ANALYSIS_SCHEMA_INVALID,
            message="역제안 비교를 완료하지 못했습니다. 잠시 후 다시 확인해 주세요.",
        )


class ModusignRequestFailed(ApiException):
    def __init__(self) -> None:
        super().__init__(
            status_code=502,
            code=ErrorCode.MODUSIGN_REQUEST_FAILED,
            message="Unable to create the signature request.",
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

