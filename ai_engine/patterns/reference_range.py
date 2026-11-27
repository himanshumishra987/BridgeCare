"""Reference-range parsing and safe point-level status evaluation."""

import re
from typing import Optional

from ai_engine.schemas.reconciliation import BiomarkerDataPoint

_RANGE_BETWEEN_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(-?\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)
_RANGE_UPPER_RE = re.compile(r"^\s*(<=|<)\s*(-?\d+(?:\.\d+)?)\s*$")
_RANGE_LOWER_RE = re.compile(r"^\s*(>=|>)\s*(-?\d+(?:\.\d+)?)\s*$")


def parse_reference_range(
    range_str: Optional[str],
) -> Optional[tuple[Optional[float], Optional[float]]]:
    """Parse an explicitly documented reference range string into (low, high) bounds.

    Never invents reference ranges when missing or unparseable.
    """
    if not range_str or not range_str.strip():
        return None

    cleaned = range_str.strip()
    m = _RANGE_BETWEEN_RE.match(cleaned)
    if m:
        low, high = float(m.group(1)), float(m.group(2))
        if low <= high:
            return (low, high)
        return None

    m = _RANGE_UPPER_RE.match(cleaned)
    if m:
        return (None, float(m.group(2)))

    m = _RANGE_LOWER_RE.match(cleaned)
    if m:
        return (float(m.group(2)), None)

    return None


def classify_point_status(
    point: BiomarkerDataPoint,
) -> tuple[Optional[str], bool]:
    """Evaluate whether a biomarker observation is 'low', 'high', 'abnormal', or 'normal'.

    Returns (status, derived_from_range). Uses documented reference_range first,
    then explicit abnormal_flag. Returns (None, False) if neither is available.
    """
    bounds = parse_reference_range(point.reference_range)
    if bounds is not None and point.numeric_value is not None:
        low, high = bounds
        if low is not None and point.numeric_value < low:
            return ("low", True)
        if high is not None and point.numeric_value > high:
            return ("high", True)
        return ("normal", True)

    flag = (point.abnormal_flag or "").strip().lower()
    if flag in ("low", "l", "below"):
        return ("low", False)
    if flag in ("high", "h", "elevated", "above"):
        return ("high", False)
    if flag in ("abnormal", "critical", "crit", "positive"):
        return ("abnormal", False)
    if flag in ("normal", "n", "within range"):
        return ("normal", False)

    return (None, False)
