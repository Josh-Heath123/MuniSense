"""One walker over cited values, and proof that it visits every cited field (P4-3, TD-16).

The model types that can hold a `Cited` value are found by inspecting the classes, never
from a list kept by hand. Every such type must have an instance in `_instances()`, so a new
component (or any new model with a cited field) fails this test until an example is added.
The walker's count for each instance is then compared with an independent count: the
`Cited`-shaped objects in the instance's JSON.
"""

import dataclasses
import importlib
import json
import pkgutil
import types
import typing
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args, get_origin

import pytest
from pydantic import BaseModel

import munisense
from munisense.catalogue.suppliers import SupplierCatalogue
from munisense.domain.base import DomainModel
from munisense.domain.billing import (
    BillingPeriod,
    MonthSoFar,
    PeriodTotal,
    calculate_bill,
    calculate_period,
    calculate_purchase,
)
from munisense.domain.citations import Cited, cited_statuses, iter_cited
from munisense.domain.money import Money, Quantisation, RoundingMode, VatRate
from munisense.domain.tariffs import DayType, TariffVersion
from munisense.domain.tariffs.components import Component
from munisense.provenance.drafts import load_file
from munisense.provenance.publication import TariffPublication, VatRatePublication
from support.builders import (
    fixture_billing_policy,
    fixture_blocks,
    fixture_calendar,
    fixture_fixed,
    fixture_flat,
    fixture_free_basic,
    fixture_holiday_list,
    fixture_levy,
    fixture_policy,
    fixture_season,
    fixture_seasonal,
    fixture_vat_table,
    fixture_version,
)
from support.publishing import DRAFTS

DATA = Path(__file__).resolve().parents[4] / "data"


def _import_everything() -> None:
    """Import every module of the application, so every model class exists (Alembic's
    migration scripts are not a package and are not imported)."""
    for info in pkgutil.walk_packages(munisense.__path__, f"{munisense.__name__}."):
        importlib.import_module(info.name)


def _all_models() -> set[type[DomainModel]]:
    _import_everything()
    found: set[type[DomainModel]] = set()
    pending: list[type[DomainModel]] = [DomainModel]
    while pending:
        for sub in pending.pop().__subclasses__():
            if sub not in found:
                found.add(sub)
                pending.append(sub)
    # Concrete, named models only: not `Cited` itself or its parametrisations, and not
    # private bases that are never instantiated.
    return {
        m
        for m in found
        if not issubclass(m, Cited)
        and not m.__name__.startswith("_")
        and m.__module__.startswith(munisense.__name__)
    }


def _mentions_cited(annotation: object, seen: set[object]) -> bool:
    """Whether a type annotation can contain a `Cited` value, at any depth."""
    if annotation in seen:
        return False
    seen.add(annotation)
    if isinstance(annotation, type) and issubclass(annotation, Cited):
        return True
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return any(
            _mentions_cited(field.annotation, seen) for field in annotation.model_fields.values()
        )
    origin = get_origin(annotation)
    if origin is typing.Literal:
        return False  # its arguments are values, not types
    if origin is typing.Annotated:  # nested inside another type; metadata is not a type
        return _mentions_cited(get_args(annotation)[0], seen)
    if isinstance(origin, typing.TypeAliasType):  # a parametrised `type X[T] = ...`
        return _mentions_cited(origin.__value__, seen) or any(
            _mentions_cited(arg, seen) for arg in get_args(annotation)
        )
    if origin is not None or isinstance(annotation, types.UnionType):
        return any(_mentions_cited(arg, seen) for arg in get_args(annotation))
    if isinstance(annotation, typing.TypeAliasType):
        return _mentions_cited(annotation.__value__, seen)
    if (
        isinstance(annotation, type)
        and not dataclasses.is_dataclass(annotation)
        and not typing.is_typeddict(annotation)
        and not (issubclass(annotation, tuple) and hasattr(annotation, "_fields"))
    ):
        return False  # a plain class: str, int, Decimal, date, an enum, ...
    if annotation in (None, Ellipsis) or isinstance(annotation, typing.TypeVar):
        return False
    # A forward reference, a dataclass or anything else this inspection cannot see into
    # would hide a cited field from it (and from the walker): fail loudly instead.
    msg = f"cannot inspect the annotation {annotation!r}"
    raise AssertionError(msg)


def _cited_models() -> set[type[DomainModel]]:
    return {m for m in _all_models() if _mentions_cited(m, set())}


def _instances() -> list[object]:
    """At least one instance of every model type that can hold a cited value."""
    season = fixture_season("summer", (1, 1), (12, 31), (None, "100"))
    return [
        load_file(DATA / "catalogue" / "suppliers.json", SupplierCatalogue),
        *(
            load_file(path, TariffPublication)
            for path in sorted((DATA / "tariffs").rglob("*.json"))
        ),
        *(load_file(path, VatRatePublication) for path in sorted((DATA / "vat").rglob("*.json"))),
        fixture_version(
            fixture_fixed("10.00"),
            fixture_flat("100"),
            fixture_blocks(("50", "100"), (None, "200"), name="blocks"),
            fixture_seasonal(season, name="seasonal"),
            fixture_levy("5"),
            fixture_free_basic("50"),
        ),
        fixture_vat_table(),
        fixture_calendar(),
        fixture_calendar(
            holidays=fixture_holiday_list(
                (date(2026, 4, 1), date(2027, 7, 1)), (date(2026, 7, 15), DayType.SUNDAY)
            )
        ),
        *_results(),
    ]


def _results() -> list[object]:
    """Engine results carry the version's cited policies, so they hold cited values too."""
    vat = fixture_vat_table()
    version = fixture_version(
        fixture_fixed("10.00"),
        fixture_flat("100"),
        policy=fixture_policy(
            prepaid_kwh=Quantisation(step=Decimal("0.01"), mode=RoundingMode.DOWN)
        ),
        billing=fixture_billing_policy(),
    )
    july = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))
    used = PeriodTotal(kwh=Decimal(100))
    return [
        calculate_bill(version, july, used, vat),
        calculate_period([version], july, used, vat),
        calculate_purchase(
            version,
            date(2026, 7, 1),
            Money(rand=Decimal("100.00")),
            MonthSoFar(purchases=0, kwh=Decimal(0)),
            vat,
        ),
    ]


def _models_in(value: object) -> Iterator[BaseModel]:
    if isinstance(value, Cited):
        return
    if isinstance(value, BaseModel):
        yield value
        for name in type(value).model_fields:
            yield from _models_in(getattr(value, name))
    elif isinstance(value, tuple | list):
        for inner in value:
            yield from _models_in(inner)
    elif isinstance(value, dict):
        for inner in value.values():
            yield from _models_in(inner)


def _json_cited_count(value: Any) -> int:
    """`Cited` values in a model's JSON: objects with a citation and a status."""
    if isinstance(value, dict):
        if {"value", "citation", "status"} == value.keys():
            return 1
        return sum(_json_cited_count(v) for v in value.values())
    if isinstance(value, list):
        return sum(_json_cited_count(v) for v in value)
    return 0


def test_the_inspection_finds_the_types_it_must() -> None:
    """A sanity check on the inspection itself: it sees the component union and the
    other known holders of cited values."""
    cited = {m.__name__ for m in _cited_models()}
    union = get_args(get_args(Component)[0])
    assert {m.__name__ for m in union} <= cited
    assert {"TariffVersion", "VatRate", "Supplier", "Season", "Block"} <= cited


def test_every_type_that_can_hold_a_cited_value_has_an_instance() -> None:
    covered = {type(m) for i in _instances() for m in _models_in(i)}
    missing = sorted(m.__name__ for m in _cited_models() - covered)
    assert not missing, f"add an instance of each to _instances(): {missing}"


@pytest.mark.parametrize("instance", _instances(), ids=lambda i: type(i).__name__)
def test_the_walker_visits_every_cited_field(instance: object) -> None:
    for model in _models_in(instance):
        visited = list(iter_cited(model))
        assert len(visited) == _json_cited_count(model.model_dump(mode="json")), type(model)
        assert len({path for path, _ in visited}) == len(visited)
        assert cited_statuses(model) == [cited.status for _, cited in visited]


def test_the_walker_names_paths_and_looks_inside_mappings() -> None:
    rate = fixture_vat_table().rates[0]
    assert [path for path, _ in iter_cited({"x": [rate.percent]})] == ["['x'][0]"]
    assert [path for path, _ in iter_cited(rate)] == ["start_cited", "percent"]


@pytest.mark.parametrize("path", sorted(DRAFTS.rglob("*.json")), ids=lambda p: p.name)
def test_the_walker_finds_every_citation_written_in_a_draft_file(path: Path) -> None:
    """Against the file's own text, not the model's dump (moved from the citation check's
    tests in P4-3)."""
    model = load_file(path, VatRate if path.parts[-3] == "vat" else TariffVersion)
    assert len(list(iter_cited(model))) == _json_cited_count(json.loads(path.read_text("utf-8")))


@dataclasses.dataclass
class _Hidden:
    value: object


class _Named(typing.NamedTuple):
    value: object


class _Typed(typing.TypedDict):
    value: object


@pytest.mark.parametrize("annotation", ["Cited[int]", _Hidden, tuple[_Hidden, ...], _Named, _Typed])
def test_an_annotation_the_inspection_cannot_see_into_fails_loudly(annotation: object) -> None:
    """A forward reference or a dataclass could hide a cited field from the inspection and
    from the walker, so the inspection refuses it rather than answering "no"."""
    with pytest.raises(AssertionError, match="cannot inspect the annotation"):
        _mentions_cited(annotation, set())


def test_a_parametrised_type_alias_is_looked_through() -> None:
    type Pair[T] = tuple[Cited[T], T]
    assert _mentions_cited(Pair[int], set())
