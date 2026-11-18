"""Per-value provenance: a citation and a verification status for every value (ADR-0006).

`Cited[T]` wraps any domain value (a `Rate`, a block threshold, a VAT rate) with where it
is printed and how sure we are. Every cited value has a citation, whatever its status
(ADR-0006: "each value has its own citation"). A component's status is the weakest status
of its values (ADR-0004), computed with `weakest`.

These types live in the domain, not in `munisense.provenance`, because the domain may not
import outside itself and every tariff value needs them. `munisense.provenance` keeps the
source-document records and the review workflow (P2).

No personal information (ADR-0008): a verifier is a short pseudonymous handle (for example
`owner`), and a user-provided value records a category of source, never a name, address,
account or meter number.
"""

import re
from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.citations.errors import NoStatusesError, UnparameterisedCitedError

# C0 and C1 control characters (log forging, terminal escapes). Newlines are allowed only
# in printed text, which may span lines on the page.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_CONTROL_EXCEPT_NEWLINE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]")


def _no_control_characters(value: str) -> str:
    if _CONTROL.search(value):
        msg = "control characters are not allowed"
        raise ValueError(msg)
    return value


def _printed(value: str) -> str:
    if _CONTROL_EXCEPT_NEWLINE.search(value):
        msg = "control characters other than newline are not allowed"
        raise ValueError(msg)
    if not value.strip():
        msg = "printed text must contain something other than whitespace"
        raise ValueError(msg)
    return value


Text = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    AfterValidator(_no_control_characters),
]
PrintedText = Annotated[
    str, StringConstraints(min_length=1, max_length=500), AfterValidator(_printed)
]
"""Exactly as printed (not stripped), for the deterministic citation check (P2)."""
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Handle = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{1,39}$")]
"""A pseudonymous handle such as `owner` or `reviewer-1`; never a name or email."""


class Citation(DomainModel):
    """Where a value is printed: document (by SHA-256), page, table or row, and the text."""

    document_sha256: Sha256
    page: Annotated[int, Field(ge=1)]
    locator: Text
    printed_text: PrintedText


class StatusKind(StrEnum):
    """Verification status kinds, weakest first.

    `user_provided` is weakest: it has no official source. `estimated` values in P1 are
    transcribed from the official schedule but not yet checked (E29). This order is a
    proposal awaiting the owner's confirmation; results warn on every non-verified value
    whatever the order, so the order never hides a warning.
    """

    USER_PROVIDED = "user_provided"
    ESTIMATED = "estimated"
    VERIFIED = "verified"

    @property
    def rank(self) -> int:
        """Higher is stronger."""
        return _RANK[self]


_RANK = {StatusKind.USER_PROVIDED: 0, StatusKind.ESTIMATED: 1, StatusKind.VERIFIED: 2}


class TextCheck(StrEnum):
    """Outcome of the deterministic check that the printed text is on the cited page.

    Until the checker exists (P2) this is declared by the verifier, not computed.
    """

    PASSED = "passed"
    NO_TEXT_LAYER = "no_text_layer"
    """A scanned page: the check cannot run, so the human check stands alone."""


class Verified(DomainModel):
    """Checked against the source by a human (ADR-0006: an agent's check is not enough)."""

    kind: Literal[StatusKind.VERIFIED] = StatusKind.VERIFIED
    verifier: Handle
    verifier_kind: Literal["human"]
    method: Text
    verified_on: date
    text_check: TextCheck


class Estimated(DomainModel):
    """Not verified. The reason says why and what would verify it."""

    kind: Literal[StatusKind.ESTIMATED] = StatusKind.ESTIMATED
    reason: Text


class ProvidedBy(StrEnum):
    """Categories of user-supplied source. Deliberately no free text (ADR-0008)."""

    OWNER_PREPAID_RECEIPT = "owner_prepaid_receipt"
    OWNER_BILL = "owner_bill"
    PILOT_USER_BILL = "pilot_user_bill"


class UserProvided(DomainModel):
    """Supplied by a user (for example from an anonymised bill), not an official source."""

    kind: Literal[StatusKind.USER_PROVIDED] = StatusKind.USER_PROVIDED
    provided_by: ProvidedBy


VerificationStatus = Annotated[Verified | Estimated | UserProvided, Field(discriminator="kind")]


class Cited[T](DomainModel):
    """A value with its own citation and verification status.

    Use it parameterised (`Cited[Rate]`, `Cited[ExactDecimal]`). The bare class refuses to
    validate, because an unbound `T` would accept anything, including a float.
    """

    value: T
    citation: Citation
    status: VerificationStatus

    @model_validator(mode="after")
    def _refuse_unparameterised(self) -> "Cited[T]":
        # An "after" validator: a "before" one would make Pydantic re-validate nested JSON
        # in Python mode, where strict dates refuse strings.
        if type(self).__pydantic_generic_metadata__["parameters"]:
            msg = "use a parameterised Cited, for example Cited[Rate]"
            raise UnparameterisedCitedError(msg)
        return self

    @property
    def kind(self) -> StatusKind:
        """The kind of this value's verification status."""
        return self.status.kind


def weakest(statuses: Iterable[Verified | Estimated | UserProvided]) -> StatusKind:
    """The weakest status kind in a non-empty set; refuses an empty one."""
    return weakest_kind(status.kind for status in statuses)


def weakest_kind(kinds: Iterable[StatusKind]) -> StatusKind:
    """The weakest of some status kinds; the one place the order is applied (W8)."""
    collected = list(kinds)
    if not collected:
        msg = "cannot summarise the status of no values"
        raise NoStatusesError(msg)
    return min(collected, key=lambda kind: kind.rank)


def cited_statuses(item: object) -> list[Verified | Estimated | UserProvided]:
    """Every status of every `Cited` value inside `item`, found by walking its fields.

    Walks domain models, tuples, lists and dicts; stops at each `Cited` (its value is the
    cited fact itself). Deriving statuses this way means a new cited field can never be
    left out of a component's or version's summary status.
    """
    if isinstance(item, Cited):
        return [item.status]
    if isinstance(item, DomainModel):
        return [s for name in type(item).model_fields for s in cited_statuses(getattr(item, name))]
    if isinstance(item, tuple | list):
        return [s for element in item for s in cited_statuses(element)]
    if isinstance(item, dict):
        return [s for element in item.values() for s in cited_statuses(element)]
    return []
