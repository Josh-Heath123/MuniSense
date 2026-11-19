"""Source-document manifests: `data/sources/<publisher>/sources.json` (P2-6, ADR-0012).

Each manifest lists the committed documents of one publisher, identified by SHA-256. It is
what the database's `source_document` table is loaded from (P2-11) and what the publish
step checks citations against (P2-8). The folder's README stays as the human notes; a test
checks that the two agree.
"""

from datetime import date
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.citations.model import Sha256, Text

FileName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,120}\.pdf$")]
HttpsUrl = Annotated[str, StringConstraints(pattern=r"^https://[^\s]{1,500}$")]
DecisionId = Annotated[str, StringConstraints(pattern=r"^E[0-9]{1,4}$")]


class SourceDocument(DomainModel):
    sha256: Sha256
    file: FileName
    title: Text
    url: HttpsUrl
    retrieved_on: date
    approval: DecisionId
    """The owner's decision that allowed it to be downloaded and committed."""
    pages: Annotated[int, Field(ge=1, le=10_000)]
    text_layer: bool
    """False for a scan: the citation check records `no_text_layer` (ADR-0012 section 5)."""


class SourceManifest(DomainModel):
    schema_version: int = Field(ge=1, le=1)
    publisher: Text
    documents: Annotated[tuple[SourceDocument, ...], Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def _unique(self) -> Self:
        for attribute in ("sha256", "file"):
            values = [getattr(d, attribute) for d in self.documents]
            if len(set(values)) != len(values):
                msg = f"each document's {attribute} must be unique"
                raise ValueError(msg)
        return self
