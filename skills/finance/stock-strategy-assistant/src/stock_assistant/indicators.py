from __future__ import annotations

from collections.abc import Sequence


def moving_average(values: Sequence[float], window: int) -> list[float | None]:
    if window <= 0:
        raise ValueError("window must be positive")
    result: list[float | None] = []
    for idx in range(len(values)):
        if idx + 1 < window:
            result.append(None)
        else:
            result.append(sum(values[idx + 1 - window:idx + 1]) / window)
    return result


def rolling_max(values: Sequence[float], window: int, shift: int = 0) -> list[float | None]:
    if window <= 0:
        raise ValueError("window must be positive")
    if shift < 0:
        raise ValueError("shift must be non-negative")
    result: list[float | None] = []
    for idx in range(len(values)):
        end = idx + 1 - shift
        start = end - window
        if start < 0 or end <= 0:
            result.append(None)
        else:
            result.append(max(values[start:end]))
    return result


def expma(values: Sequence[float], span: int) -> list[float]:
    if span <= 0:
        raise ValueError("span must be positive")
    if not values:
        return []
    alpha = 2 / (span + 1)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1 - alpha) * result[-1])
    return result


def is_limit_up(close: float, limit_up_price: float | None, tolerance: float = 0.005) -> bool:
    if limit_up_price is None or limit_up_price <= 0:
        return False
    return close >= limit_up_price * (1 - tolerance)
