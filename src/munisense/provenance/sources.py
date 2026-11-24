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
from munisense.domain.citations.model import PrintedText, Sha256, Text, normalise_whitespace

FileName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,120}\.pdf$")]
HttpsUrl = Annotated[str, StringConstraints(pattern=r"^https://[^\s]{1,500}$")]
DecisionId = Annotated[str, StringConstraints(pattern=r"^E[0-9]{1,4}$")]
MAX_DRAWN_ITEMS = 100
MAX_DRAWN_TEXTS = 50


class DrawnItem(DomainModel):
    """Something drawn on a page, not printed as text, and the texts a citation may give
    for it (ADR-0016 point 5). A citation flagged `drawn` matches one of `texts` only
    exactly, after the citation check's whitespace rule; never as a substring or pattern.

    The list is a trusted input of the citation check and the publication guards: it
    changes only in a pull request that adds no publication."""

    page: Annotated[int, Field(ge=1)]
    what: Text
    """What is drawn there, and how a text below is read from it."""
    texts: Annotated[tuple[PrintedText, ...], Field(min_length=1, max_length=MAX_DRAWN_TEXTS)]


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
    drawn: (
        Annotated[tuple[DrawnItem, ...], Field(min_length=1, max_length=MAX_DRAWN_ITEMS)] | None
    ) = Field(default=None, exclude_if=lambda value: value is None)
    """Items drawn on pages of a document with a text layer (ADR-0016 point 5); omitted
    when absent (ADR-0016 point 3)."""

    @model_validator(mode="after")
    def _drawn_items(self) -> Self:
        if self.drawn is None:
            return self
        if not self.text_layer:
            msg = "drawn items are listed only for a document with a text layer"
            raise ValueError(msg)
        seen: set[tuple[int, str]] = set()
        for item in self.drawn:
            if item.page > self.pages:
                msg = f"a drawn item is on page {item.page}, past the document's {self.pages}"
                raise ValueError(msg)
            for text in item.texts:
                key = (item.page, normalise_whitespace(text))
                if key in seen:
                    msg = f"a drawn text on page {item.page} is listed twice"
                    raise ValueError(msg)
                seen.add(key)
        return self

    def drawn_texts(self, page: int) -> frozenset[str]:
        """The allowed drawn texts on `page`, whitespace-normalised."""
        return frozenset(
            normalise_whitespace(text)
            for item in self.drawn or ()
            if item.page == page
            for text in item.texts
        )


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
