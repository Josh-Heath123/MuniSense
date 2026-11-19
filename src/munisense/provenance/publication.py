"""Publications: a tariff version or VAT rate in its envelope (ADR-0012, sections 1 to 3).

A publication file is the canonical JSON (`munisense.provenance.canonical`) of one of:

- `TariffPublication`: a `TariffVersion`, or `null` for a withdrawal;
- `VatRatePublication`: one `VatRate`, or `null` for a withdrawal.

The envelope's `publication` record carries the record time (`published_at`) and only the
publish step's own automatic results (`checks`); human verification lives in each value's
`Verified` status. The identity rules of ADR-0012 are checked here:

- the id is `<scope>/<code>/<effective-from>/r<N>`, and matches the content it holds;
- a first publication (`r1`) supersedes nothing; every later revision supersedes the
  revision before it of the same tariff (`r<N-1>`), possibly filed under another date;
- a withdrawal has no version, supersedes something, and is filed under the same date.

Whether the superseded publication exists, is not itself a withdrawal and is superseded only
once is a property of the whole set of files; the publish step and the loader check it.
"""

import re
from collections.abc import Callable
from datetime import date
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.citations.model import Handle, Text
from munisense.domain.money import VatRate
from munisense.domain.tariffs import TariffVersion
from munisense.provenance import canonical

ID_PATTERN = (
    r"^([a-z0-9][a-z0-9_-]{0,63})/([a-z0-9][a-z0-9_-]{0,63})/(\d{4}-\d{2}-\d{2})/r([1-9]\d{0,3})$"
)
PublicationId = Annotated[str, StringConstraints(pattern=ID_PATTERN)]

VAT_SCOPE = "vat"
VAT_CODE = "south-africa"
SCHEMA_VERSIONS = (1,)


class PublicationError(ValueError):
    """A publication file is malformed, or its identity does not match its content."""


class ParsedId(DomainModel):
    scope: str
    code: str
    effective_from: date
    revision: int

    @classmethod
    def of(cls, publication_id: str) -> "ParsedId":
        match = re.fullmatch(ID_PATTERN, publication_id)
        if match is None:
            msg = f"not a publication id: {publication_id!r}"
            raise PublicationError(msg)
        scope, code, day, revision = match.groups()
        return cls(
            scope=scope, code=code, effective_from=date.fromisoformat(day), revision=int(revision)
        )

    @property
    def key(self) -> tuple[str, str]:
        return (self.scope, self.code)


class CitationCheckCounts(DomainModel):
    """How many cited values each outcome had. A publication never has a failure."""

    passed: Annotated[int, Field(ge=0)]
    no_text_layer: Annotated[int, Field(ge=0)]
    failed: Literal[0]


class PublishChecks(DomainModel):
    """The publish step's own automatic results, recorded when it wrote the file."""

    tool_version: Text
    schema_valid: Literal[True]
    documents_listed_and_hashes_match: Literal[True]
    overlaps: Literal["none"]
    citation_check: CitationCheckCounts


class PublicationRecord(DomainModel):
    id: PublicationId
    published_at: AwareDatetime
    published_by: Handle
    supersedes: PublicationId | None
    reason: Text
    checks: PublishChecks

    @model_validator(mode="after")
    def _revision_chain(self) -> Self:
        own = ParsedId.of(self.id)
        if self.supersedes is None:
            if own.revision != 1:
                msg = f"{self.id}: a revision after r1 must supersede the revision before it"
                raise ValueError(msg)
            return self
        previous = ParsedId.of(self.supersedes)
        if previous.key != own.key:
            msg = f"{self.id}: may supersede only a publication of the same tariff"
            raise ValueError(msg)
        if own.revision != previous.revision + 1:
            msg = f"{self.id}: must be the revision after {self.supersedes}"
            raise ValueError(msg)
        return self


def _check_withdrawal(record: PublicationRecord) -> None:
    if record.supersedes is None:
        msg = f"{record.id}: a withdrawal must name the publication it withdraws"
        raise ValueError(msg)
    if ParsedId.of(record.supersedes).effective_from != ParsedId.of(record.id).effective_from:
        msg = f"{record.id}: a withdrawal is filed under the withdrawn version's date"
        raise ValueError(msg)


class TariffPublication(DomainModel):
    schema_version: Literal[1]
    publication: PublicationRecord
    version: TariffVersion | None

    @property
    def is_withdrawal(self) -> bool:
        return self.version is None

    @model_validator(mode="after")
    def _identity(self) -> Self:
        own = ParsedId.of(self.publication.id)
        if own.scope == VAT_SCOPE:
            msg = f"{self.publication.id}: a tariff publication cannot use the VAT scope"
            raise ValueError(msg)
        if self.version is None:
            _check_withdrawal(self.publication)
            return self
        holds = (self.version.supplier, self.version.tariff_code, self.version.effective_from.value)
        if (own.scope, own.code, own.effective_from) != holds:
            msg = f"{self.publication.id}: the id does not match the version it holds"
            raise ValueError(msg)
        return self


class VatRatePublication(DomainModel):
    schema_version: Literal[1]
    publication: PublicationRecord
    version: VatRate | None

    @property
    def is_withdrawal(self) -> bool:
        return self.version is None

    @model_validator(mode="after")
    def _identity(self) -> Self:
        own = ParsedId.of(self.publication.id)
        if own.key != (VAT_SCOPE, VAT_CODE):
            msg = f"{self.publication.id}: a VAT publication's id starts with vat/south-africa/"
            raise ValueError(msg)
        if self.version is None:
            _check_withdrawal(self.publication)
            return self
        if own.effective_from != self.version.start:
            msg = f"{self.publication.id}: the id does not match the rate's start date"
            raise ValueError(msg)
        return self


Publication = TariffPublication | VatRatePublication

# One converter per older schema version, each turning that version's JSON into the current
# one. Only version 1 exists, so there is nothing to convert yet (ADR-0012, section 1).
CONVERTERS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {1: lambda value: value}


def load[P: (TariffPublication, VatRatePublication)](text: str, kind: type[P]) -> P:
    """Check canonical form, convert from the file's schema version, then validate."""
    value = canonical.check(text)
    if not isinstance(value, dict):
        msg = "a publication file holds one JSON object"
        raise PublicationError(msg)
    version = value.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version not in CONVERTERS:
        msg = f"unknown schema_version {version!r}; known: {sorted(CONVERTERS)}"
        raise PublicationError(msg)
    return kind.model_validate_json(canonical.dumps(CONVERTERS[version](value)))


def render(publication: Publication) -> str:
    """The canonical text of a publication, keys in the models' own order."""
    return canonical.dumps(canonical.parse(publication.model_dump_json()))
