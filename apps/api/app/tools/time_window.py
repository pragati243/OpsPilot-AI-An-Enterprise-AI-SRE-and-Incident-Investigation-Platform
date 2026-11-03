import re
from datetime import timedelta

from app.tools.exceptions import ToolError

_PATTERN = re.compile(r"^(\d+)([mhd])$")
_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}

MIN_WINDOW = timedelta(minutes=1)
MAX_WINDOW = timedelta(days=7)


class InvalidTimeWindowError(ToolError):
    pass


def parse_time_window(value: str) -> timedelta:
    """Parse a bounded, Grafana-style time window like '15m', '1h', '2d'.

    Bounded on purpose: this is one of the concrete limits that keep a tool
    call cheap and finite, per the workflow's execution-budget requirements.
    """
    match = _PATTERN.match(value.strip())
    if not match:
        raise InvalidTimeWindowError(
            f"invalid time_window {value!r}; expected a format like '15m', '1h', or '2d'"
        )
    amount, unit = match.groups()
    delta = timedelta(seconds=int(amount) * _UNIT_SECONDS[unit])
    if delta < MIN_WINDOW or delta > MAX_WINDOW:
        raise InvalidTimeWindowError(
            f"time_window {value!r} out of bounds: must be between "
            f"{MIN_WINDOW} and {MAX_WINDOW}"
        )
    return delta
