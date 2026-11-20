"""Publications: a tariff version or VAT rate in its envelope (ADR-0012, sections 1 to 3).

A publication file is the canonical JSON (`munisense.provenance.canonical`) of one of:

- `TariffPublication`: a `TariffVersion`, or `null` for a withdrawal;
- `VatRatePublication`: one `VatRate`, or `null` for a withdrawal.

The envelope's `publication` record carries the record time (`published_at`) and only the
publish step's own automatic results (`checks`); human verification lives in each value's
`Verified` status. The identity rules of ADR-0012 are checked here:

- the id is `<scope>/<code>/<effective-from>/r<N>` (ASCII digits only), and matches the
  content it holds;
- a publication may supersede only a publication of the same tariff; its revision number is
  the next free one under the date it is filed under (ADR-0013), which only the whole set of
  files can show;
- a withdrawal has no version, supersedes something, is filed under the same date, and
  records `WithdrawalChecks`; a version records `PublishChecks` (ADR-0013).

Rules about the whole set of files are not visible to one file: the superseded publication
exists, is not a withdrawal and has only this successor; the file's path agrees with its id;
the revision is the next free one, with no gaps. The publish step (P2-8), the CI check
(P2-9) and the loader (P2-11) check them.

`load` raises `CanonicalJsonError`, `PublicationError` (both `ProvenanceError`) or Pydantic's
`ValidationError`.
"""

import re
from collections.abc import Callable
from datetime import date
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.citations.model import Handle, Text
from munisense.domain.money import VatRate
from munisense.domain.tariffs import TariffVersion
from munisense.provenance import canonical
from munisense.provenance.errors import PublicationError

# ASCII digits only (`[0-9]`, never `\\d`, which also matches other scripts' digits).
_CODE = r"[a-z0-9][a-z0-9_-]{0,63}"
ID_PATTERN = rf"^({_CODE})/({_CODE})/([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})/r([1-9][0-9]{{0,3}})$"
PublicationId = Annotated[str, StringConstraints(pattern=ID_PATTERN)]

VAT_SCOPE = "vat"
VAT_CODE = "south-africa"


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
        try:
            effective_from = date.fromisoformat(day)
        except ValueError:
            msg = f"not a valid date in publication id: {publication_id!r}"
            raise PublicationError(msg) from None
        return cls(scope=scope, code=code, effective_from=effective_from, revision=int(revision))

    @property
    def key(self) -> tuple[str, str]:
        return (self.scope, self.code)


class CitationCheckCounts(DomainModel):
    """How many cited values each outcome had. A publication never has a failure."""

    passed: Annotated[int, Field(ge=0)]
    no_text_layer: Annotated[int, Field(ge=0)]
    failed: Literal[0]


class PublishChecks(DomainModel):
    """The publish step's own automatic results, recorded when it wrote the file.

    The keys are those of ADR-0012's example. `schema` is held as `schema_check`, because
    Pydantic models already have a `schema` attribute; the file still says `schema`.
    """

    model_config = ConfigDict(
        **DomainModel.model_config,
        validate_by_alias=True,
        validate_by_name=False,
        serialize_by_alias=True,
    )

    kind: Literal["version"] = "version"
    tool_version: Text
    schema_check: Annotated[Literal["valid"], Field(alias="schema")]
    documents: Literal["all cited documents in a manifest; hashes match"]
    overlap: Literal["none"]
    citation_check: CitationCheckCounts


class WithdrawalChecks(DomainModel):
    """What the publish step checks for a withdrawal (ADR-0013): the withdrawn publication
    exists, is not a withdrawal and has no successor."""

    kind: Literal["withdrawal"] = "withdrawal"
    tool_version: Text
    withdrawn: Literal["exists and is current"]


class PublicationRecord(DomainModel):
    id: PublicationId
    published_at: AwareDatetime
    published_by: Handle
    supersedes: PublicationId | None
    reason: Text
    checks: Annotated[PublishChecks | WithdrawalChecks, Field(discriminator="kind")]

    @model_validator(mode="after")
    def _revision_chain(self) -> Self:
        own = ParsedId.of(self.id)
        if self.supersedes is not None and ParsedId.of(self.supersedes).key != own.key:
            msg = f"{self.id}: may supersede only a publication of the same tariff"
            raise ValueError(msg)
        return self


def _check_kind(record: PublicationRecord, *, withdrawal: bool) -> None:
    if withdrawal != isinstance(record.checks, WithdrawalChecks):
        what = (
            "a withdrawal records withdrawal checks"
            if withdrawal
            else "a version records version checks"
        )
        msg = f"{record.id}: {what}"
        raise ValueError(msg)


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
        _check_kind(self.publication, withdrawal=self.version is None)
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
        _check_kind(self.publication, withdrawal=self.version is None)
        if self.version is None:
            _check_withdrawal(self.publication)
            return self
        if own.effective_from != self.version.start:
            msg = f"{self.publication.id}: the id does not match the rate's start date"
            raise ValueError(msg)
        return self


Publication = TariffPublication | VatRatePublication

# For each known schema version, a function from that version's JSON to the current one's.
# The current version maps to itself. Only version 1 exists. When version 2 arrives: each
# converter goes straight to the current version, takes the publication kind into account,
# and is tested against every committed file of its version (ADR-0012, section 1).
CONVERTERS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {1: lambda value: value}


def load[P: (TariffPublication, VatRatePublication)](text: str, kind: type[P]) -> P:
    """Check canonical form, convert from the file's schema version, then validate.

    `text` is the decoded file; `load_bytes` reads a file's bytes as strict UTF-8.
    """
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


def load_bytes[P: (TariffPublication, VatRatePublication)](data: bytes, kind: type[P]) -> P:
    """`load` for a file's bytes: strict UTF-8 without a byte-order mark."""
    canonical.check_bytes(data)
    return load(data.decode("utf-8"), kind)
