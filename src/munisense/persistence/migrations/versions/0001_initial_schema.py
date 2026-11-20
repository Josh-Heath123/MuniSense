"""The first schema: catalogue, sources, publications, versions (P2-10; ADR-0003, ADR-0012).

The database is a projection of the committed files: the loader (P2-11) inserts final rows
and nothing is ever updated, so the application role has `SELECT` only (P2-3). Two
exclusion constraints (`btree_gist`, created by the bootstrap) refuse two versions of one
tariff, or two VAT rates, whose valid periods and record periods both overlap, so every
past snapshot is free of overlaps too.

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


def upgrade() -> None:  # one table after another
    op.create_table(
        "supplier",
        sa.Column("code", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("tariff_year_start_month", sa.SmallInteger, nullable=False),
        sa.CheckConstraint("code ~ '^[a-z0-9][a-z0-9_-]{0,63}$'", name="supplier_code"),
        sa.CheckConstraint(
            "kind IN ('municipality', 'municipal_utility', 'eskom')", name="supplier_kind"
        ),
        sa.CheckConstraint("tariff_year_start_month BETWEEN 1 AND 12", name="supplier_start_month"),
        schema=SCHEMA,
    )
    op.create_table(
        "customer_class",
        sa.Column(
            "supplier_code", sa.Text, sa.ForeignKey(f"{SCHEMA}.supplier.code"), primary_key=True
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
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_by", sa.Text, nullable=False),
        sa.Column("supersedes", sa.Text, sa.ForeignKey(f"{SCHEMA}.publication.id"), nullable=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("is_withdrawal", sa.Boolean, nullable=False),
        sa.Column("checks", postgresql.JSONB, nullable=False),
        sa.CheckConstraint("revision >= 1", name="publication_revision"),
        sa.UniqueConstraint(
            "scope", "code", "effective_from", "revision", name="publication_place_unique"
        ),
        schema=SCHEMA,
    )
    # A publication is superseded at most once (ADR-0012).
    op.create_index(
        "publication_one_successor",
        "publication",
        ["supersedes"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("supersedes IS NOT NULL"),
    )
    op.create_table(
        "tariff_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "publication_id",
            sa.Text,
            sa.ForeignKey(f"{SCHEMA}.publication.id"),
            nullable=False,
            unique=True,
        ),
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
        sa.CheckConstraint("NOT isempty(valid_period)", name="tariff_version_valid_period"),
        sa.CheckConstraint("NOT isempty(recorded_during)", name="tariff_version_recorded_during"),
        sa.CheckConstraint(f"status IN {STATUSES}", name="tariff_version_status"),
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
        sa.Column(
            "publication_id",
            sa.Text,
            sa.ForeignKey(f"{SCHEMA}.publication.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("country", sa.Text, nullable=False),
        sa.Column("valid_period", postgresql.DATERANGE, nullable=False),
        sa.Column("recorded_during", postgresql.TSTZRANGE, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.CheckConstraint("NOT isempty(valid_period)", name="vat_rate_valid_period"),
        sa.CheckConstraint("NOT isempty(recorded_during)", name="vat_rate_recorded_during"),
        sa.CheckConstraint(f"status IN {STATUSES}", name="vat_rate_status"),
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
