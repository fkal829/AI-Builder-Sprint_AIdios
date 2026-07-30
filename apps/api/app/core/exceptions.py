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


class ExternalStorageFailure(RuntimeError):
    """Private storage or metadata persistence failed without exposing vendor details."""

