"""Per-value provenance: a citation and a verification status for every value (ADR-0006).

`Cited[T]` wraps any domain value (a `Rate`, a block threshold, a VAT rate) with where it
came from and how sure we are. A component's status is the weakest status of its values
(ADR-0004), computed with `weakest`.

These types live in the domain, not in `munisense.provenance`, because the domain may not
import outside itself and every tariff value needs them. `munisense.provenance` keeps the
source-document records and the review workflow (P2).
"""

from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.citations.errors import NoStatusesError

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
PrintedText = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class Citation(DomainModel):
    """Where a value is printed: document (by SHA-256), page, table or row, and the text."""

    document_sha256: Sha256
    page: Annotated[int, Field(ge=1)]
    locator: Text
    printed_text: PrintedText
    """The value exactly as printed, for the deterministic citation check (P2)."""


class StatusKind(StrEnum):
    """Verification status kinds, weakest first."""

    ESTIMATED = "estimated"
    USER_PROVIDED = "user_provided"
    VERIFIED = "verified"

    @property
    def rank(self) -> int:
        """Higher is stronger. Estimated is weakest; user-provided is weaker than verified."""
        return list(StatusKind).index(self)


class TextCheck(StrEnum):
    """Outcome of the deterministic check that the printed text is on the cited page."""

    PASSED = "passed"
    NO_TEXT_LAYER = "no_text_layer"
    """A scanned page: the check cannot run, so a human check stands in for it."""


class Verified(DomainModel):
    """Checked against the source: a deterministic text check (or a scan) plus a verifier."""

    kind: Literal[StatusKind.VERIFIED] = StatusKind.VERIFIED
    verifier: Text
    method: Text
    verified_on: date
    text_check: TextCheck


class Estimated(DomainModel):
    """Not verified. The reason says why and what would verify it."""

    kind: Literal[StatusKind.ESTIMATED] = StatusKind.ESTIMATED
    reason: Text


class UserProvided(DomainModel):
    """Supplied by a user (for example from a bill), not from an official source."""

    kind: Literal[StatusKind.USER_PROVIDED] = StatusKind.USER_PROVIDED
    provided_by: Text


VerificationStatus = Annotated[Verified | Estimated | UserProvided, Field(discriminator="kind")]


class Cited[T](DomainModel):
    """A value with its own citation and verification status.

    A `verified` value must have a citation. An `estimated` or `user_provided` value may
    lack one (for example a rounding rule inferred from bills); its status then explains.
    """

    value: T
    citation: Citation | None
    status: VerificationStatus

    @model_validator(mode="after")
    def _verified_needs_a_citation(self) -> Self:
        if isinstance(self.status, Verified) and self.citation is None:
            msg = "a verified value must cite its source"
            raise ValueError(msg)
        return self

    @property
    def kind(self) -> StatusKind:
        return self.status.kind


def weakest(statuses: Iterable[Verified | Estimated | UserProvided]) -> StatusKind:
    """The weakest status kind in a non-empty set; refuses an empty one."""
    kinds = [status.kind for status in statuses]
    if not kinds:
        msg = "cannot summarise the status of no values"
        raise NoStatusesError(msg)
    return min(kinds, key=lambda kind: kind.rank)
