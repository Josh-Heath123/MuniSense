"""The loader and `poe db-rebuild`: the database rebuilt from the committed files (P2-11).

ADR-0003 and ADR-0012 section 6. The rebuild:

1. refuses a database whose name does not end in `_dev` or `_test`;
2. checks every file before touching the database: the publication guards' checks (canonical
   and valid, at their own paths, catalogue, supersede chains, revisions without gaps, record
   order; `munisense.ingestion.guards`), every committed source document's SHA-256 against
   its manifest (a document listed twice is refused), every citation's document listed in a
   manifest (ADR-0012 section 4), and that a tariff keeps one customer class;
3. brings the schema to head (Alembic, as the migration role);
4. in one transaction, refuses a schema whose tables differ from `TABLES`, empties every
   table and loads the catalogue, the source documents, the tariffs, and then the
   publications in record order (`published_at`, then id: a supersede must name a row
   already inserted, and the foreign key is not deferrable) with their version rows; then
   checks the loaded rows (every non-withdrawal publication has its version row, record
   time starts at `published_at`, a version's tariff or country is its publication's).
   Any error rolls the whole load back, leaving the previous contents.

Nothing comes from a clock, randomness or a sequence: a publication's key is its id, other
keys are UUIDv5 of it, and `recorded_during` runs from `published_at` to the `published_at`
of the publication that supersedes or withdraws it (or is open). Two rebuilds from the same
files give identical rows.

Two departures from ADR-0012 section 6, put to the owner as W22: the tables are emptied and
refilled in one transaction rather than the schema dropped and recreated (the migration role
may not create a schema, and a failed load keeps the previous contents), and publications
load in record order rather than sorted path order (the order the foreign keys need).
"""

import hashlib
import os
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from pydantic import BaseModel
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from munisense.catalogue.suppliers import SupplierCatalogue
from munisense.domain.citations import cited_statuses, weakest
from munisense.domain.money import VatRate
from munisense.domain.tariffs import TariffVersion
from munisense.ingestion.citation_check import iter_cited
from munisense.ingestion.guards import Loaded, check_set, load_all
from munisense.ingestion.publish import documents
from munisense.persistence.connection import engine
from munisense.platform.settings import DatabaseUrl, SettingsError, database_url
from munisense.provenance import canonical
from munisense.provenance.drafts import load_file
from munisense.provenance.errors import ProvenanceError
from munisense.provenance.publication import VAT_SCOPE, ParsedId
from munisense.provenance.sources import SourceManifest

ROOT = Path(__file__).resolve().parents[3]
NAMESPACE = uuid.UUID("8f0c7f7e-4b1e-5b5a-9a51-6d756e697365")  # fixed: keys must not change
TABLES = (  # children first, for emptying
    "tariff_component",
    "tariff_version",
    "vat_rate",
    "publication",
    "tariff",
    "customer_class",
    "source_document",
    "supplier",
)


class LoadError(Exception):
    """The files cannot be loaded. `problems` lists every reason found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Summary:
    publications: int
    tariff_versions: int
    vat_rates: int
    documents: int


def key(*parts: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, "/".join(parts))


def _json(model: BaseModel) -> str:
    return model.model_dump_json()


def _status(item: object) -> str:
    return weakest(cited_statuses(item)).value


def _document_problems(data: Path, loaded: list[Loaded]) -> list[str]:
    """Every listed document present with its hash; every citation's document listed."""
    listed = documents(data)  # refuses a document listed in two manifests
    problems = []
    for path, document in listed.values():
        if not path.is_file():
            problems.append(f"{path.relative_to(data)}: listed but missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != document.sha256:
            problems.append(f"{path.relative_to(data)}: its SHA-256 differs from the manifest")
    cited: list[tuple[str, BaseModel]] = [
        (
            "catalogue/suppliers.json",
            load_file(data / "catalogue" / "suppliers.json", SupplierCatalogue),
        )
    ]
    cited += [(p.id, p.publication) for p in loaded]
    for where, model in cited:
        for field, value in iter_cited(model):
            if value.citation.document_sha256 not in listed:
                problems.append(
                    f"{where}: {field} cites document {value.citation.document_sha256},"
                    " which no source manifest lists"
                )
    return problems


def _class_problems(loaded: list[Loaded]) -> list[str]:
    classes: dict[tuple[str, str], set[str]] = {}
    for publication in loaded:
        version = publication.publication.version
        if isinstance(version, TariffVersion):
            classes.setdefault(publication.key, set()).add(version.customer_class)
    return [
        f"{scope}/{code}: one tariff keeps one customer class, not {', '.join(sorted(found))}"
        for (scope, code), found in sorted(classes.items())
        if len(found) > 1
    ]


def check(data: Path) -> list[Loaded]:
    """Every check that needs no database. Raises `LoadError` with every problem found."""
    try:
        loaded, problems = load_all(data)
        problems += check_set(data, loaded)
        problems += _document_problems(data, loaded)
        problems += _class_problems(loaded)
    except (ProvenanceError, ValueError, OSError) as error:
        raise LoadError([f"{type(error).__name__}: {str(error)[:300]}"]) from None
    if problems:
        raise LoadError(problems)
    return loaded


def _insert(connection: Connection, table: str, row: Mapping[str, object]) -> None:
    columns = ", ".join(row)
    values = ", ".join(f":{name}" for name in row)
    connection.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({values})"), dict(row))  # noqa: S608


def _recorded_during(publication: Loaded, successors: dict[str, Loaded]) -> str:
    start = publication.published_at.isoformat()
    after = successors.get(publication.id)
    end = after.published_at.isoformat() if after is not None else ""
    return f"[{start},{end})"


def _load(connection: Connection, data: Path, loaded: list[Loaded]) -> Summary:
    catalogue = load_file(data / "catalogue" / "suppliers.json", SupplierCatalogue)
    for supplier in catalogue.suppliers:
        _insert(
            connection,
            "supplier",
            {
                "code": supplier.code,
                "name": supplier.name,
                "kind": supplier.kind.value,
                "tariff_year_start_month": supplier.tariff_year_start_month.value,
                "status": _status(supplier),
                "payload": _json(supplier),
            },
        )
    documents = 0
    for manifest_path in sorted((data / "sources").glob("*/sources.json")):
        manifest = load_file(manifest_path, SourceManifest)
        for document in manifest.documents:
            _insert(
                connection,
                "source_document",
                {
                    "sha256": document.sha256,
                    "publisher": manifest.publisher,
                    "file": document.file,
                    "title": document.title,
                    "url": document.url,
                    "retrieved_on": document.retrieved_on,
                    "approval": document.approval,
                    "pages": document.pages,
                    "text_layer": document.text_layer,
                },
            )
            documents += 1
    ordered = sorted(loaded, key=lambda p: (0 if p.key[0] == VAT_SCOPE else 1, str(p.path)))
    successors = {p.supersedes: p for p in loaded if p.supersedes is not None}
    tariffs: set[tuple[str, str]] = set()
    for publication in ordered:
        version = publication.publication.version
        if isinstance(version, TariffVersion) and publication.key not in tariffs:
            supplier_code, code = publication.key
            classes = {"supplier_code": supplier_code, "code": version.customer_class}
            exists = connection.execute(
                text("SELECT 1 FROM customer_class WHERE supplier_code = :s AND code = :c"),
                {"s": supplier_code, "c": version.customer_class},
            ).first()
            if exists is None:
                _insert(connection, "customer_class", classes)
            _insert(
                connection,
                "tariff",
                {
                    "id": key("tariff", supplier_code, code),
                    "supplier_code": supplier_code,
                    "tariff_code": code,
                    "customer_class_code": version.customer_class,
                },
            )
            tariffs.add(publication.key)
    # Publications in record order, so a supersede always names a row already inserted.
    counts = {"tariff": 0, "vat": 0}
    for publication in sorted(ordered, key=lambda p: (p.published_at, p.id)):
        record = publication.publication.publication
        parsed = ParsedId.of(record.id)
        version = publication.publication.version
        _insert(
            connection,
            "publication",
            {
                "id": record.id,
                "kind": "vat" if parsed.scope == VAT_SCOPE else "tariff",
                "scope": parsed.scope,
                "code": parsed.code,
                "effective_from": parsed.effective_from,
                "revision": parsed.revision,
                "published_at": record.published_at,
                "published_by": record.published_by,
                "supersedes": record.supersedes,
                "reason": record.reason,
                "is_withdrawal": version is None,
                "checks": canonical.dumps(
                    canonical.parse(record.checks.model_dump_json(by_alias=True))
                ),
            },
        )
        if version is None:
            continue
        common = {
            "id": key("version", record.id),
            "publication_id": record.id,
            "recorded_during": _recorded_during(publication, successors),
            "schema_version": publication.publication.schema_version,
            "status": _status(version),
            "payload": _json(version),
        }
        if isinstance(version, VatRate):
            end = version.end.isoformat() if version.end is not None else ""
            _insert(
                connection,
                "vat_rate",
                {
                    **common,
                    "country": parsed.code,
                    "valid_period": f"[{version.start.isoformat()},{end})",
                },
            )
            counts["vat"] += 1
            continue
        end = version.effective_to.value.isoformat() if version.effective_to else ""
        _insert(
            connection,
            "tariff_version",
            {
                **common,
                "tariff_id": key("tariff", *publication.key),
                "valid_period": f"[{version.effective_from.value.isoformat()},{end})",
            },
        )
        for position, component in enumerate(version.components):
            _insert(
                connection,
                "tariff_component",
                {
                    "tariff_version_id": common["id"],
                    "position": position,
                    "name": component.name,
                    "kind": component.kind,
                    "status": _status(component),
                    "payload": _json(component),
                },
            )
        counts["tariff"] += 1
    return Summary(len(loaded), counts["tariff"], counts["vat"], documents)


# Each query returns the publications that break one rule; all must return nothing.
ROW_CHECKS = {
    "has no version row": (
        "SELECT p.id FROM publication p WHERE NOT p.is_withdrawal"
        " AND NOT EXISTS (SELECT 1 FROM tariff_version v WHERE v.publication_id = p.id)"
        " AND NOT EXISTS (SELECT 1 FROM vat_rate r WHERE r.publication_id = p.id)"
    ),
    "has record time that does not start at its published_at": (
        "SELECT p.id FROM publication p JOIN ("
        " SELECT publication_id, recorded_during FROM tariff_version"
        " UNION ALL SELECT publication_id, recorded_during FROM vat_rate) v"
        " ON v.publication_id = p.id WHERE lower(v.recorded_during) <> p.published_at"
    ),
    "has a version of another tariff": (
        "SELECT p.id FROM publication p JOIN tariff_version v ON v.publication_id = p.id"
        " JOIN tariff t ON t.id = v.tariff_id"
        " WHERE t.supplier_code <> p.scope OR t.tariff_code <> p.code"
    ),
    "has a VAT rate of another country": (
        "SELECT p.id FROM publication p JOIN vat_rate r ON r.publication_id = p.id"
        " WHERE r.country <> p.code"
    ),
}


def _row_problems(connection: Connection) -> list[str]:
    return [
        f"{found} {rule}"
        for rule, sql in ROW_CHECKS.items()
        for found in connection.execute(text(sql)).scalars()
    ]


def _table_problems(connection: Connection) -> list[str]:
    found = set(
        connection.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'munisense'"
                " AND tablename <> 'alembic_version'"
            )
        ).scalars()
    )
    if found == set(TABLES):
        return []
    return [f"the schema's tables {sorted(found)} differ from the loader's {sorted(TABLES)}"]


class _RefusedError(Exception):
    """Raised inside the transaction so that it rolls back."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems


def _alembic(url: DatabaseUrl) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "src/munisense/persistence/migrations"))
    config.attributes["url"] = url
    return config


def rebuild(data: Path, url: DatabaseUrl) -> Summary:
    """Rebuild the database at `url` from the files under `data`, or refuse."""
    if not url.database.endswith(("_dev", "_test")):
        msg = f"refusing to rebuild {url.database!r}: the name must end in '_dev' or '_test'"
        raise LoadError([msg])
    loaded = check(data)
    command.upgrade(_alembic(url), "head")
    target = engine(url)
    try:
        with target.begin() as connection:
            if problems := _table_problems(connection):
                raise _RefusedError(problems)
            for table in TABLES:
                connection.execute(text(f"DELETE FROM {table}"))  # noqa: S608
            summary = _load(connection, data, loaded)
            if problems := _row_problems(connection):
                raise _RefusedError(problems)
            return summary
    except _RefusedError as refused:  # the transaction is rolled back: nothing changed
        raise LoadError(refused.problems) from None
    except DBAPIError as error:  # the transaction is rolled back: nothing changed
        diag = getattr(error.orig, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
        raise LoadError(
            [f"the database refused or failed the load ({constraint or type(error.orig).__name__})"]
        ) from None
    finally:
        target.dispose()


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] = os.environ) -> int:
    if argv:
        sys.stderr.write("db-rebuild takes no arguments\n")
        return 2
    try:
        url = database_url(env, "MUNISENSE_MIGRATION_DATABASE_URL")
        summary = rebuild(Path.cwd() / "data", url)
    except SettingsError as error:
        sys.stderr.write(f"db-rebuild: {error}\n")
        return 2
    except LoadError as refused:
        sys.stderr.write("db-rebuild refused:\n" + "".join(f"  - {p}\n" for p in refused.problems))
        return 1
    sys.stdout.write(
        f"db-rebuild: {url.database} rebuilt: {summary.publications} publications"
        f" ({summary.tariff_versions} tariff versions, {summary.vat_rates} VAT rates),"
        f" {summary.documents} source documents\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover  # the command line runs main()
    raise SystemExit(main(sys.argv[1:]))
