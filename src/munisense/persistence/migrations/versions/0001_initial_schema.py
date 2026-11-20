"""The first schema: catalogue, sources, publications, versions (P2-10; ADR-0003, ADR-0012).

The database is a projection of the committed files: the loader (P2-11) inserts final rows
and nothing is ever updated, so the application role has `SELECT` only (P2-3). The
database itself enforces what it cheaply can (ADR-0003):

- two exclusion constraints (`btree_gist`, created by the bootstrap) refuse two versions of
  one tariff, or two VAT rates of one country, whose valid periods and record periods both
  overlap, so every past snapshot is free of overlaps too;
- ranges are non-empty, start at a known moment, and are `[lower, upper)`;
- a publication's id agrees with its place (ADR-0013's unique place), a withdrawal
  supersedes something, nothing supersedes itself, a publication supersedes only one of
  the same tariff and never a withdrawal, and is superseded at most once;
- a version row belongs to a publication of its own kind that is not a withdrawal.

Left to the loader (P2-11; TD-17): that every publication that is not a withdrawal has
its version row (it would need a deferred trigger).

Revision ID: 0001
Revises:
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "munisense"
STATUSES = "('verified', 'estimated', 'user_provided')"


def _ranges(table: str) -> list[sa.CheckConstraint]:
    """Non-empty, `[lower, upper)`, and starting at a known moment."""
    return [
        sa.CheckConstraint(
            "NOT isempty(valid_period) AND NOT lower_inf(valid_period)"
            " AND lower_inc(valid_period) AND NOT upper_inc(valid_period)",
            name=f"{table}_valid_period",
        ),
        sa.CheckConstraint(
            "NOT isempty(recorded_during) AND NOT lower_inf(recorded_during)"
            " AND lower_inc(recorded_during) AND NOT upper_inc(recorded_during)",
            name=f"{table}_recorded_during",
        ),
    ]


def _version_columns(kind: str) -> list[sa.Column[object]]:
    """Constant columns that let a composite foreign key tie a version row to a publication
    of its own kind that is not a withdrawal."""
    return [
        sa.Column("publication_kind", sa.Text, nullable=False, server_default=kind),
        sa.Column("publication_is_withdrawal", sa.Boolean, nullable=False, server_default="false"),
    ]


def _version_constraints(table: str, kind: str) -> list[sa.Constraint]:
    return [
        sa.CheckConstraint(f"publication_kind = '{kind}'", name=f"{table}_publication_kind"),
        sa.CheckConstraint("NOT publication_is_withdrawal", name=f"{table}_not_withdrawal"),
        sa.ForeignKeyConstraint(
            ["publication_id", "publication_kind", "publication_is_withdrawal"],
            [
                f"{SCHEMA}.publication.id",
                f"{SCHEMA}.publication.kind",
                f"{SCHEMA}.publication.is_withdrawal",
            ],
            name=f"{table}_publication",
        ),
        sa.CheckConstraint(f"status IN {STATUSES}", name=f"{table}_status"),
        *_ranges(table),
    ]


def upgrade() -> None:
    op.create_table(
        "supplier",
        sa.Column("code", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("tariff_year_start_month", sa.SmallInteger, nullable=False),
        # The supplier as the model writes it: the start month keeps its citation (rule 1).
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.CheckConstraint("code ~ '^[a-z0-9][a-z0-9_-]{0,63}$'", name="supplier_code"),
        sa.CheckConstraint(
            "kind IN ('municipality', 'municipal_utility', 'eskom')", name="supplier_kind"
        ),
        sa.CheckConstraint("tariff_year_start_month BETWEEN 1 AND 12", name="supplier_start_month"),
        sa.CheckConstraint(f"status IN {STATUSES}", name="supplier_status"),
        schema=SCHEMA,
    )
    op.create_table(
        "customer_class",
        sa.Column(
            "supplier_code",
            sa.Text,
            sa.ForeignKey(f"{SCHEMA}.supplier.code"),
            primary_key=True,
        ),
        sa.Column("code", sa.Text, primary_key=True),
        schema=SCHEMA,
    )
    op.create_table(
        "tariff",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("supplier_code", sa.Text, nullable=False),
        sa.Column("tariff_code", sa.Text, nullable=False),
        sa.Column("customer_class_code", sa.Text, nullable=False),
        sa.UniqueConstraint("supplier_code", "tariff_code", name="tariff_code_unique"),
        sa.ForeignKeyConstraint(
            ["supplier_code", "customer_class_code"],
            [f"{SCHEMA}.customer_class.supplier_code", f"{SCHEMA}.customer_class.code"],
            name="tariff_customer_class",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "source_document",
        sa.Column("sha256", sa.Text, primary_key=True),
        sa.Column("publisher", sa.Text, nullable=False),
        sa.Column("file", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("retrieved_on", sa.Date, nullable=False),
        sa.Column("approval", sa.Text, nullable=False),
        sa.Column("pages", sa.Integer, nullable=False),
        sa.Column("text_layer", sa.Boolean, nullable=False),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="source_document_sha256"),
        sa.CheckConstraint("pages > 0", name="source_document_pages"),
        schema=SCHEMA,
    )
    op.create_table(
        "publication",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_by", sa.Text, nullable=False),
        sa.Column("supersedes", sa.Text, nullable=True),
        # Constant: a composite foreign key below refuses superseding a withdrawal.
        sa.Column("supersedes_withdrawal", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("is_withdrawal", sa.Boolean, nullable=False),
        sa.Column("checks", postgresql.JSONB, nullable=False),
        sa.CheckConstraint("revision >= 1", name="publication_revision"),
        sa.CheckConstraint(
            "id = scope || '/' || code || '/' || to_char(effective_from, 'YYYY-MM-DD')"
            " || '/r' || revision",
            name="publication_id_is_its_place",
        ),
        sa.CheckConstraint(
            "kind = CASE WHEN scope = 'vat' THEN 'vat' ELSE 'tariff' END",
            name="publication_kind",
        ),
        sa.CheckConstraint(
            "NOT is_withdrawal OR supersedes IS NOT NULL", name="publication_withdrawal"
        ),
        sa.CheckConstraint("supersedes <> id", name="publication_not_itself"),
        sa.CheckConstraint("NOT supersedes_withdrawal", name="publication_supersedes_flag"),
        sa.UniqueConstraint(
            "scope", "code", "effective_from", "revision", name="publication_place_unique"
        ),
        sa.UniqueConstraint("id", "kind", "is_withdrawal", name="publication_id_kind"),
        sa.UniqueConstraint("id", "scope", "code", "is_withdrawal", name="publication_id_place"),
        # Same tariff, and never a withdrawal (ADR-0012 section 3, P2-4).
        sa.ForeignKeyConstraint(
            ["supersedes", "scope", "code", "supersedes_withdrawal"],
            [
                f"{SCHEMA}.publication.id",
                f"{SCHEMA}.publication.scope",
                f"{SCHEMA}.publication.code",
                f"{SCHEMA}.publication.is_withdrawal",
            ],
            name="publication_supersedes",
        ),
        schema=SCHEMA,
    )
    # A publication is superseded at most once (ADR-0012).
    op.create_index(
        "publication_one_successor", "publication", ["supersedes"], unique=True, schema=SCHEMA
    )
    op.create_table(
        "tariff_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("publication_id", sa.Text, nullable=False, unique=True),
        *_version_columns("tariff"),
        sa.Column(
            "tariff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.tariff.id"),
            nullable=False,
        ),
        sa.Column("valid_period", postgresql.DATERANGE, nullable=False),
        sa.Column("recorded_during", postgresql.TSTZRANGE, nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        *_version_constraints("tariff_version", "tariff"),
        postgresql.ExcludeConstraint(
            ("tariff_id", "="),
            ("valid_period", "&&"),
            ("recorded_during", "&&"),
            name="tariff_version_no_overlap",
            using="gist",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "tariff_component",
        sa.Column(
            "tariff_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.tariff_version.id"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.UniqueConstraint("tariff_version_id", "name", name="tariff_component_name_unique"),
        sa.CheckConstraint(f"status IN {STATUSES}", name="tariff_component_status"),
        schema=SCHEMA,
    )
    op.create_table(
        "vat_rate",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("publication_id", sa.Text, nullable=False, unique=True),
        *_version_columns("vat"),
        sa.Column("country", sa.Text, nullable=False),
        sa.Column("valid_period", postgresql.DATERANGE, nullable=False),
        sa.Column("recorded_during", postgresql.TSTZRANGE, nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        *_version_constraints("vat_rate", "vat"),
        postgresql.ExcludeConstraint(
            ("country", "="),
            ("valid_period", "&&"),
            ("recorded_during", "&&"),
            name="vat_rate_no_overlap",
            using="gist",
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    for table in (
        "vat_rate",
        "tariff_component",
        "tariff_version",
        "publication",
        "source_document",
        "tariff",
        "customer_class",
        "supplier",
    ):
        op.drop_table(table, schema=SCHEMA)
