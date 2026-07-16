class ErrorCode:
    """Stable codes owned by the backend's shared API boundary."""

    ERROR = 'error'
    INVALID = 'invalid'
    AUTHENTICATION_FAILED = 'authentication_failed'
    PERMISSION_DENIED = 'permission_denied'
    NOT_FOUND = 'not_found'
    CONFLICT = 'conflict'
    SERVICE_UNAVAILABLE = 'service_unavailable'
    REQUEST_TOO_LARGE = 'request_too_large'
    SERVER_ERROR = 'server_error'

    ALL = (
        ERROR,
        INVALID,
        AUTHENTICATION_FAILED,
        PERMISSION_DENIED,
        NOT_FOUND,
        CONFLICT,
        SERVICE_UNAVAILABLE,
        REQUEST_TOO_LARGE,
        SERVER_ERROR,
    )
