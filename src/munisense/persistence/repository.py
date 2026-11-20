"""Read the database "as recorded on" a moment (P2-12; ADR-0003, ADR-0012 sections 2 and 4).

Every query names two times: the valid date (when a price applies) and the record moment
(what MuniSense believed then). A row answers when its `valid_period` contains the date and
its `recorded_during` contains the moment; the exclusion constraints guarantee at most one
tariff version per tariff and one VAT rate per country and date at any record moment.

Payloads are read back through the domain models, so a version from the database is the
version that was published. The functions take a connection, which should be the
application role's (`SELECT` only), and never write.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Connection, text

from munisense.domain.citations import StatusKind
from munisense.domain.money import VatRate, VatTable
from munisense.domain.tariffs import TariffVersion


class NotRecordedError(LookupError):
    """Nothing was recorded for the question, or what was recorded cannot answer it."""


@dataclass(frozen=True)
class RecordedVersion:
    """A tariff version as recorded, with the publication that recorded it."""

    publication_id: str
    published_at: datetime
    version: TariffVersion


@dataclass(frozen=True)
class CitedValue:
    """One cited value found by a citation or status query, as stored (JSON)."""

    publication_id: str
    value: dict[str, Any]


def _moment(recorded_on: datetime) -> datetime:
    if recorded_on.tzinfo is None or recorded_on.utcoffset() is None:
        msg = "a record moment needs a time zone (it is compared with published_at)"
        raise ValueError(msg)
    return recorded_on


def tariff_version(
    connection: Connection, supplier: str, tariff: str, on: date, recorded_on: datetime
) -> RecordedVersion:
    """The version of `supplier`/`tariff` valid on `on`, as recorded on `recorded_on`.

    A withdrawn version and one never recorded both raise `NotRecordedError` (TD-18).
    """
    if isinstance(on, datetime):
        msg = "the valid date must be a date, not a datetime"
        raise TypeError(msg)
    row = connection.execute(
        text(
            "SELECT p.id, p.published_at, v.payload FROM tariff_version v"
            " JOIN tariff t ON t.id = v.tariff_id JOIN publication p ON p.id = v.publication_id"
            " WHERE t.supplier_code = :supplier AND t.tariff_code = :tariff"
            " AND v.valid_period @> :on AND v.recorded_during @> :at"
        ),
        {"supplier": supplier, "tariff": tariff, "on": on, "at": _moment(recorded_on)},
    ).one_or_none()
    if row is None:
        msg = f"no version of {supplier}/{tariff} valid on {on} was recorded on {recorded_on}"
        raise NotRecordedError(msg)
    version = TariffVersion.model_validate_json(json.dumps(row.payload))
    return RecordedVersion(row.id, row.published_at, version)


def vat_table(connection: Connection, country: str, recorded_on: datetime) -> VatTable:
    """Every VAT rate of `country` recorded on `recorded_on`, as a `VatTable`.

    Refuses when none is recorded, or when the rates do not form a contiguous table (a gap;
    they cannot overlap at one record moment: the exclusion constraint refuses that).
    """
    payloads = connection.execute(
        text(
            "SELECT payload FROM vat_rate WHERE country = :country AND recorded_during @> :at"
            " ORDER BY lower(valid_period)"
        ),
        {"country": country, "at": _moment(recorded_on)},
    ).scalars()
    rates = tuple(VatRate.model_validate_json(json.dumps(p)) for p in payloads)
    if not rates:
        msg = f"no VAT rate of {country} was recorded on {recorded_on}"
        raise NotRecordedError(msg)
    try:
        return VatTable(rates=rates)
    except ValidationError as error:
        msg = f"the VAT rates of {country} recorded on {recorded_on} do not form a contiguous table"
        raise NotRecordedError(msg) from error


# Both version tables, current at the record moment; JSONB path queries walk the payloads.
_CURRENT = (
    "SELECT publication_id, payload FROM tariff_version WHERE recorded_during @> :at"
    " UNION ALL SELECT publication_id, payload FROM vat_rate WHERE recorded_during @> :at"
)


def _cited(
    connection: Connection, path: str, variables: dict[str, object], at: datetime
) -> list[CitedValue]:
    rows = connection.execute(
        text(
            f"SELECT c.publication_id, found FROM ({_CURRENT}) c,"  # noqa: S608  # fixed text
            " jsonb_path_query(c.payload, CAST(:path AS jsonpath), CAST(:vars AS jsonb)) found"
            " ORDER BY c.publication_id"
        ),
        {"at": _moment(at), "path": path, "vars": json.dumps(variables)},
    )
    return [CitedValue(row.publication_id, row.found) for row in rows]


def values_citing(
    connection: Connection, document_sha256: str, page: int, recorded_on: datetime
) -> list[CitedValue]:
    """Every cited value that cites `page` of the document, in versions recorded then."""
    return _cited(
        connection,
        "strict $.** ? (@.citation.document_sha256 == $document && @.citation.page == $page)",
        {"document": document_sha256, "page": page},
        recorded_on,
    )


def values_with_status(
    connection: Connection, status: StatusKind, recorded_on: datetime
) -> list[CitedValue]:
    """Every cited value with the given status, in versions recorded then."""
    return _cited(
        connection,
        "strict $.** ? (@.status.kind == $kind && exists(@.citation))",
        {"kind": status.value},
        recorded_on,
    )
