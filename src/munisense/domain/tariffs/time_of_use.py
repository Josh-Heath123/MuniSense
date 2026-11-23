"""Time-of-use names shared by consumption input, the calendar and components (ADR-0016)."""

from enum import StrEnum


class TouPeriod(StrEnum):
    """A time-of-use period, as a calendar names its time ranges (ADR-0016 point 1)."""

    PEAK = "peak"
    STANDARD = "standard"
    OFF_PEAK = "off_peak"
