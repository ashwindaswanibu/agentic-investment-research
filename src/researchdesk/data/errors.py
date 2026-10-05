from researchdesk.errors import DomainError


class DataError(DomainError):
    """Stable, user-visible data boundary failure; never an empty success result."""

    def __init__(self, code: str, message: str, status_code: int = 502):
        super().__init__(code, message, status_code)
