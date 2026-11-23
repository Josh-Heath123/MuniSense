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
    TouPeriod,
)
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
    with pytest.raises(HolidayCoverageError, match="outside the dates the holiday list covers"):
        calendar.period_for(day, 0)


def test_a_listed_holiday_outside_the_window_is_refused() -> None:
    with pytest.raises(ValidationError, match="outside the list's coverage: 2027-07-01"):
        fixture_holiday_list(COVERAGE, (date(2027, 7, 1), DayType.SUNDAY))


def test_a_holiday_listed_twice_is_refused() -> None:
    with pytest.raises(ValidationError, match="listed once"):
        fixture_holiday_list(
            COVERAGE, (date(2026, 7, 15), DayType.SUNDAY), (date(2026, 7, 15), DayType.SATURDAY)
        )


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


def test_holidays_by_day_of_week_have_no_list() -> None:
    with pytest.raises(ValidationError, match="no list or coverage"):
        HolidayTreatment(rule=_cited_rule(HolidayRule.AS_DAY_OF_WEEK), coverage=LISTED.coverage)
    with pytest.raises(ValidationError, match="no list or coverage"):
        HolidayTreatment(rule=_cited_rule(HolidayRule.AS_DAY_OF_WEEK), listed=LISTED.listed)


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
    monkeypatch.setattr(FlatEnergy, "NEEDS_CALENDAR", True)
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
    with pytest.raises(ValidationError, match="'high' of energy covers different days"):
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
    test checks every publication byte for byte)."""
    for path in sorted((Path(__file__).resolve().parents[4] / "data" / "tariffs").rglob("*.json")):
        publication = load_bytes(path.read_bytes(), TariffPublication)
        assert publication.version is not None
        assert publication.version.tou_calendar is None
        assert render(publication).encode("utf-8") == path.read_bytes()
