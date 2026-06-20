"""Business-facing API errors."""


class BusinessValidationError(ValueError):
    """The request is syntactically valid but violates product rules."""
