from fastapi import HTTPException


class ARSError(HTTPException):
    pass


class NotFoundError(ARSError):
    def __init__(self, detail: str = "Not found"):
        super().__init__(status_code=404, detail=detail)


class ConflictError(ARSError):
    """Invalid state transition or duplicate action."""

    def __init__(self, detail: str = "Conflict"):
        super().__init__(status_code=409, detail=detail)


class BadRequestError(ARSError):
    def __init__(self, detail: str = "Bad request"):
        super().__init__(status_code=400, detail=detail)


class AuthError(ARSError):
    """Signature verification failed."""

    def __init__(self, detail: str = "Invalid signature"):
        super().__init__(status_code=401, detail=detail)


class ForbiddenError(ARSError):
    """Actor not authorized for this action."""

    def __init__(self, detail: str = "Forbidden"):
        super().__init__(status_code=403, detail=detail)
