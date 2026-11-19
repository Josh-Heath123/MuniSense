"""Errors raised on purpose by the provenance package (P2-4)."""


class ProvenanceError(ValueError):
    """Root of the errors this package raises on purpose."""


class CanonicalJsonError(ProvenanceError):
    """The bytes or text are not JSON, hold a refused value, or are not in canonical form."""


class PublicationError(ProvenanceError):
    """A publication file is malformed, or its identity does not match its content."""
