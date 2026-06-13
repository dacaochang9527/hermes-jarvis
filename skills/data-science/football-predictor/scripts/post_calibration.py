"""Probability post-calibration helpers."""

from __future__ import annotations


def shrink_binary_probability(probability: float, base_rate: float, shrinkage: float) -> float:
    """Shrink a binary probability toward a historical base rate.

    shrinkage=0 keeps the model probability; shrinkage=1 returns the base rate.
    """
    if not 0.0 <= shrinkage <= 1.0:
        raise ValueError("shrinkage must be between 0 and 1")
    probability = max(min(probability, 1.0), 0.0)
    base_rate = max(min(base_rate, 1.0), 0.0)
    return probability * (1.0 - shrinkage) + base_rate * shrinkage


def calibrate_over_under(
    over_probability: float,
    base_over_rate: float = 0.45,
    shrinkage: float = 0.45,
) -> tuple[float, float]:
    """Return calibrated over/under probabilities that sum to 1."""
    calibrated_over = shrink_binary_probability(over_probability, base_over_rate, shrinkage)
    calibrated_under = 1.0 - calibrated_over
    return calibrated_over, calibrated_under
