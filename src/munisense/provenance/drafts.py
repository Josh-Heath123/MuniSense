"""Reading committed data files in canonical form (P2-6, ADR-0012 sections 1 and 7).

Drafts are bare versions (`TariffVersion` or one `VatRate`), the supplier catalogue and the
source manifests. Every one is canonical JSON, checked on its bytes before its model reads it.
"""

from pathlib import Path

from pydantic import BaseModel

from munisense.domain.money import VatRate, VatTable
from munisense.provenance import canonical
from munisense.provenance.errors import ProvenanceError


def load_file[M: BaseModel](path: Path, model: type[M]) -> M:
    """Read `path` as strict, canonical UTF-8 JSON, then validate it with `model`."""
    data = path.read_bytes()
    canonical.check_bytes(data)
    return model.model_validate_json(data)


def write_file(path: Path, value: BaseModel) -> None:
    """Write `value` in canonical form, in the model's own key order."""
    text = canonical.dumps(canonical.parse(value.model_dump_json()))
    path.write_bytes(text.encode("utf-8"))  # bytes: no newline translation on any platform


def load_vat_table(folder: Path) -> VatTable:
    """Assemble a VAT table from one-rate drafts named `<start>.json`, in date order."""
    rates = []
    for path in sorted(folder.glob("*.json")):
        rate = load_file(path, VatRate)
        if path.stem != rate.start.isoformat():
            msg = f"{path.name}: a VAT draft is named after its start date, {rate.start}"
            raise ProvenanceError(msg)
        rates.append(rate)
    return VatTable(rates=tuple(rates))
