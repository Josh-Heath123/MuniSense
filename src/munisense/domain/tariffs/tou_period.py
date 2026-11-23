"""The names of time-of-use periods (ADR-0016), in a module of their own so that both the
components and the calendar can use them."""

from enum import StrEnum


class TouPeriod(StrEnum):
    """A time-of-use period, as a calendar names its time ranges (ADR-0016 point 1)."""

    PEAK = "peak"
    STANDARD = "standard"
    OFF_PEAK = "off_peak"
