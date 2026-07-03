"""Imperal SDK error hierarchy.

All SDK errors inherit from ImperalError. HTTP-level errors inherit from APIError.
Catch ImperalError to handle any SDK error. Catch APIError for HTTP-specific errors.
"""


class ImperalError(Exception):
    """Base error for all SDK errors."""
    def __init__(self, message: str, code: str = "unknown"):
        self.message = message
        self.code = code
        super().__init__(message)


class APIError(ImperalError):
    """Error from Auth Gateway / API calls."""
    def __init__(self, message: str, status_code: int, code: str = "api_error"):
        self.status_code = status_code
        super().__init__(message, code)


class NotFoundError(APIError):
    """Resource not found (404)."""
    def __init__(self, resource: str, id: str):
        self.resource = resource
        self.id = id
        super().__init__(f"{resource} '{id}' not found", 404, "not_found")


class RateLimitError(APIError):
    """Rate limited (429). Check retry_after for wait time."""
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s", 429, "rate_limited")


class AuthError(ImperalError):
    """Authentication or authorization error."""
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message, "auth_error")


class ValidationError(ImperalError):
    """Input validation failed."""
    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(f"Validation error on '{field}': {message}", "validation_error")


class ExtensionError(ImperalError):
    """Error within extension execution."""
    def __init__(self, app_id: str, message: str):
        self.app_id = app_id
        super().__init__(f"Extension '{app_id}': {message}", "extension_error")


class QuotaExceededError(ImperalError):
    """Billing quota exceeded."""
    def __init__(self, resource: str, limit: int):
        self.resource = resource
        self.limit = limit
        super().__init__(f"Quota exceeded for {resource} (limit: {limit})", "quota_exceeded")


class SkeletonAccessForbidden(PermissionError):
    """Raised when ctx.skeleton is accessed outside a @ext.skeleton tool.

    Skeleton is the LLM-facts snapshot consumed by the intent classifier.
    Use ctx.cache for short-lived runtime data (<= 300s) or ctx.store for
    persistent per-user state.

    I-SKELETON-LLM-ONLY.
    """
