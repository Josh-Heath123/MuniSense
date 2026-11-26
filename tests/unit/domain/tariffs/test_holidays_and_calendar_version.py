"""Holiday treatment, the calendar on a tariff version, and TD-11 (P4-6, ADR-0016).

Dates and hours here are fixtures, not any supplier's (CLAUDE.md rule 1).
"""

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from munisense.domain.citations import Cited
from munisense.domain.tariffs import (
    DayType,
    FlatEnergy,
    HolidayCoverageError,
    HolidayRule,
    HolidayTreatment,
    ListedHoliday,
    TariffVersion,
    TouPeriod,
)
from munisense.provenance import canonical
from munisense.provenance.publication import TariffPublication, load_bytes, render
from support.builders import (
    FIXTURE_STATUS,
    fixture_calendar,
    fixture_citation,
    fixture_flat,
    fixture_holiday_list,
    fixture_season,
    fixture_seasonal,
    fixture_version,
)

# A made-up list in the shape of Eskom's Appendix D: a coverage window, and each listed
# holiday treated as a Saturday or a Sunday.
COVERAGE = (date(2026, 4, 1), date(2027, 7, 1))
LISTED = fixture_holiday_list(
    COVERAGE,
    (date(2026, 7, 15), DayType.SUNDAY),  # a Wednesday, treated as a Sunday
    (date(2026, 12, 16), DayType.SATURDAY),  # a Wednesday, treated as a Saturday
)


def test_holidays_as_the_day_of_week_change_nothing() -> None:
    calendar = fixture_calendar()
    assert calendar.holidays.rule.value == HolidayRule.AS_DAY_OF_WEEK
    assert calendar.day_type(date(2026, 12, 16)) == DayType.WEEKDAY
    assert calendar.day_type(date(2031, 1, 1)) == DayType.WEEKDAY  # no list, no window


def test_a_listed_holiday_takes_its_listed_treatment() -> None:
    calendar = fixture_calendar(holidays=LISTED)
    assert calendar.day_type(date(2026, 7, 15)) == DayType.SUNDAY
    assert calendar.day_type(date(2026, 12, 16)) == DayType.SATURDAY
    # the Sunday schedule's hours apply on the listed Wednesday (high season)
    assert calendar.period_for(date(2026, 7, 15), 19 * 60) == TouPeriod.OFF_PEAK
    assert calendar.period_for(date(2026, 7, 22), 19 * 60) == TouPeriod.PEAK  # a normal Wednesday


def test_an_unlisted_day_inside_the_window_is_its_day_of_the_week() -> None:
    calendar = fixture_calendar(holidays=LISTED)
    assert calendar.day_type(date(2026, 7, 16)) == DayType.WEEKDAY
    assert calendar.day_type(date(2026, 7, 18)) == DayType.SATURDAY


@pytest.mark.parametrize("day", [date(2026, 3, 31), date(2027, 7, 1), date(2030, 1, 1)])
def test_a_day_outside_the_lists_window_is_refused(day: date) -> None:
    """Nothing can tell whether it is a holiday, so the engine does not guess."""
    calendar = fixture_calendar(holidays=LISTED)
    with pytest.raises(
        HolidayCoverageError, match="outside the dates the holiday list covers"
    ) as caught:
        calendar.period_for(day, 0)
    assert str(day) not in str(caught.value)  # the day may come from a consumer's readings


def test_a_listed_holiday_outside_the_window_is_refused() -> None:
    with pytest.raises(ValidationError, match="outside the list's coverage: 2027-07-01"):
        fixture_holiday_list(COVERAGE, (date(2027, 7, 1), DayType.SUNDAY))


@pytest.mark.parametrize(
    "holidays",
    [
        ((date(2026, 7, 15), DayType.SUNDAY), (date(2026, 7, 15), DayType.SATURDAY)),  # twice
        ((date(2026, 12, 16), DayType.SATURDAY), (date(2026, 7, 15), DayType.SUNDAY)),  # order
    ],
)
def test_holidays_are_listed_once_each_in_date_order(
    holidays: tuple[tuple[date, DayType], ...],
) -> None:
    """One encoding per meaning, and an easier list to check against its source."""
    with pytest.raises(ValidationError, match="in date order, each date once"):
        fixture_holiday_list(COVERAGE, *holidays)


def test_a_listed_holiday_is_treated_as_a_saturday_or_a_sunday() -> None:
    with pytest.raises(ValidationError, match="Saturday or a Sunday"):
        ListedHoliday(day=date(2026, 7, 15), treated_as=DayType.WEEKDAY)


def _cited_rule(rule: HolidayRule) -> Cited[HolidayRule]:
    return Cited[HolidayRule](value=rule, citation=fixture_citation(), status=FIXTURE_STATUS)


def test_a_list_needs_its_coverage_holidays_and_unlisted_rule() -> None:
    with pytest.raises(ValidationError, match="needs its coverage"):
        HolidayTreatment(rule=_cited_rule(HolidayRule.LISTED))
    with pytest.raises(ValidationError, match="needs its coverage"):
        HolidayTreatment(
            rule=_cited_rule(HolidayRule.LISTED), coverage=LISTED.coverage, unlisted=LISTED.unlisted
        )
    with pytest.raises(ValidationError, match="needs its coverage"):
        HolidayTreatment(
            rule=_cited_rule(HolidayRule.LISTED), coverage=LISTED.coverage, listed=LISTED.listed
        )


def test_holidays_by_day_of_week_have_no_list() -> None:
    with pytest.raises(ValidationError, match="no list or coverage"):
        HolidayTreatment(rule=_cited_rule(HolidayRule.AS_DAY_OF_WEEK), coverage=LISTED.coverage)
    with pytest.raises(ValidationError, match="no list or coverage"):
        HolidayTreatment(rule=_cited_rule(HolidayRule.AS_DAY_OF_WEEK), listed=LISTED.listed)
    with pytest.raises(ValidationError, match="no list or coverage"):
        HolidayTreatment(rule=_cited_rule(HolidayRule.AS_DAY_OF_WEEK), unlisted=LISTED.unlisted)


# ----------------------------------------------------------- the calendar on a version


def test_a_version_may_carry_a_calendar() -> None:
    version = fixture_version(fixture_flat("100"), tou_calendar=fixture_calendar())
    assert version.tou_calendar is not None


def test_a_version_without_a_calendar_leaves_it_out_of_its_output() -> None:
    """ADR-0016 point 3: absent means omitted, so files without one stay byte-identical."""
    without = fixture_version(fixture_flat("100"))
    assert "tou_calendar" not in without.model_dump_json()
    with_one = fixture_version(fixture_flat("100"), tou_calendar=fixture_calendar())
    assert '"tou_calendar":' in with_one.model_dump_json()


def test_a_component_that_needs_a_calendar_is_refused_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No component needs one yet (P4-7 adds `TimeOfUseEnergy`); the rule is shown with a
    component marked as needing one."""
    monkeypatch.setattr(FlatEnergy, "needs_calendar", property(lambda self: True))
    with pytest.raises(ValidationError, match="energy need a time-of-use calendar"):
        fixture_version(fixture_flat("100"))
    assert fixture_version(fixture_flat("100"), tou_calendar=fixture_calendar())


# ------------------------------------------------------------------------------- TD-11


def test_a_seasonal_component_that_agrees_with_the_calendar_is_accepted() -> None:
    seasonal = fixture_seasonal(
        fixture_season("high", (6, 1), (8, 31), (None, "300")),
        fixture_season("low", (9, 1), (5, 31), (None, "200")),
    )
    version = fixture_version(seasonal, tou_calendar=fixture_calendar())
    assert version.tou_calendar is not None


def test_a_seasonal_season_with_other_days_is_refused() -> None:
    """TD-11: two calendars in one version could disagree; now they must not."""
    seasonal = fixture_seasonal(
        fixture_season("high", (5, 1), (8, 31), (None, "300")),
        fixture_season("low", (9, 1), (4, 30), (None, "200")),
    )
    with pytest.raises(
        ValidationError, match="'high' of energy has dates that differ from the calendar's"
    ):
        fixture_version(seasonal, tou_calendar=fixture_calendar())


def test_a_seasonal_season_missing_from_the_calendar_is_refused() -> None:
    seasonal = fixture_seasonal(
        fixture_season("high", (6, 1), (8, 31), (None, "300")),
        fixture_season("winter", (9, 1), (5, 31), (None, "200")),
    )
    with pytest.raises(
        ValidationError, match="'winter' of energy is not in the version's calendar"
    ):
        fixture_version(seasonal, tou_calendar=fixture_calendar())


def test_the_published_tariff_b_files_load_unchanged() -> None:
    """They have no calendar; they load, and render to the same bytes (the committed-data
    test checks every publication byte for byte). Only Ekurhuleni's Tariff B files: other
    publications (Eskom's Homeflex) carry a calendar, and adding them must not break this
    test (E63)."""
    folder = Path(__file__).resolve().parents[4] / "data" / "tariffs" / "city-of-ekurhuleni"
    paths = sorted(folder.glob("b-residential-*/*.json"))
    assert len(paths) >= 2
    for path in paths:
        publication = load_bytes(path.read_bytes(), TariffPublication)
        assert publication.version is not None
        assert publication.version.tou_calendar is None
        assert render(publication).encode("utf-8") == path.read_bytes()


def test_without_a_calendar_two_seasonal_components_must_agree() -> None:
    """TD-11 also for a version with no calendar: one season name, one set of dates."""
    first = fixture_seasonal(
        fixture_season("high", (6, 1), (8, 31), (None, "300")),
        fixture_season("low", (9, 1), (5, 31), (None, "200")),
        name="energy",
    )
    second = fixture_seasonal(
        fixture_season("high", (5, 1), (8, 31), (None, "30")),
        fixture_season("low", (9, 1), (4, 30), (None, "20")),
        name="network",
    )
    with pytest.raises(
        ValidationError, match="'high' of network has dates that differ from another"
    ):
        fixture_version(first, second)


# --------------------------------------------- a holiday list must cover the version


def test_a_holiday_list_must_cover_every_day_of_the_version() -> None:
    """The fixture version runs from 1 July 2026 to 1 July 2027; COVERAGE covers it."""
    assert fixture_version(fixture_flat("100"), tou_calendar=fixture_calendar(holidays=LISTED))
    short = fixture_holiday_list(
        (date(2026, 4, 1), date(2027, 4, 1)), (date(2026, 7, 15), DayType.SUNDAY)
    )
    with pytest.raises(ValidationError, match="must cover every day of the version"):
        fixture_version(fixture_flat("100"), tou_calendar=fixture_calendar(holidays=short))
    late = fixture_holiday_list(
        (date(2026, 8, 1), date(2027, 7, 1)), (date(2026, 8, 5), DayType.SUNDAY)
    )
    with pytest.raises(ValidationError, match="must cover every day of the version"):
        fixture_version(fixture_flat("100"), tou_calendar=fixture_calendar(holidays=late))


def test_a_holiday_list_covers_at_most_two_years() -> None:
    """A mistyped end (2072 for 2027) would otherwise price later holidays as weekdays."""
    typo = fixture_holiday_list(
        (date(2026, 4, 1), date(2072, 7, 1)), (date(2026, 7, 15), DayType.SUNDAY)
    )
    with pytest.raises(ValidationError, match="covers at most 731 days"):
        fixture_version(fixture_flat("100"), tou_calendar=fixture_calendar(holidays=typo))
    two_years = fixture_holiday_list(
        (date(2026, 7, 1), date(2028, 7, 1)), (date(2026, 7, 15), DayType.SUNDAY)
    )
    assert fixture_version(fixture_flat("100"), tou_calendar=fixture_calendar(holidays=two_years))


def test_an_open_ended_version_cannot_carry_a_holiday_list() -> None:
    """No finite list covers it, and a mistyped end within the cap would go unnoticed."""
    with pytest.raises(ValidationError, match="needs its end date"):
        fixture_version(
            fixture_flat("100"), end=None, tou_calendar=fixture_calendar(holidays=LISTED)
        )
    assert fixture_version(fixture_flat("100"), end=None, tou_calendar=fixture_calendar())


# ------------------------------------------------------------------ round trips


def test_a_version_with_a_listed_calendar_survives_json_and_canonical_form() -> None:
    """Strict JSON mode reads what the model writes, and the canonical text (what a
    publication file holds) parses back to the same version. The database round trip is
    P4-12's."""
    version = fixture_version(fixture_flat("100"), tou_calendar=fixture_calendar(holidays=LISTED))
    text = version.model_dump_json()
    assert TariffVersion.model_validate_json(text) == version
    canonical_text = canonical.dumps(canonical.parse(text))
    assert canonical.check(canonical_text) == canonical.parse(text)
    assert TariffVersion.model_validate_json(canonical_text) == version
