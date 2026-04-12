"""Statistical functions for context validation."""

from statistics import quantiles
from typing import NamedTuple


class BaselineStats(NamedTuple):
    """Statistics computed from baseline (reference branch) files."""

    q1: float
    q3: float
    iqr: float
    lower_fence: float
    upper_fence: float
    file_count: int


OutlierResult = tuple[list[int], list[int]]


def compute_baseline_stats(
    file_sizes: list[int],
    iqr_multiplier: float = 1.5,
) -> BaselineStats | None:
    """Compute baseline statistics (Q1, Q3, IQR, fences) from file sizes.

    Args:
        file_sizes: List of character counts from baseline files.
        iqr_multiplier: IQR multiplier for fences (1.5=mild, 3=extreme).

    Returns:
        BaselineStats with computed values, or None if insufficient data.
    """
    if len(file_sizes) < 4:
        return None

    q1, _, q3 = quantiles(file_sizes, n=4)
    iqr = q3 - q1

    if iqr == 0:
        return None

    lower_fence = q1 - iqr_multiplier * iqr
    upper_fence = q3 + iqr_multiplier * iqr

    return BaselineStats(
        q1=q1,
        q3=q3,
        iqr=iqr,
        lower_fence=lower_fence,
        upper_fence=upper_fence,
        file_count=len(file_sizes),
    )


def detect_outliers(file_sizes: list[int], iqr_multiplier: float = 1.5) -> OutlierResult:
    """Detect files that are statistical outliers using IQR method.

    Uses Tukey's fences: values outside Q1 - k*IQR or Q3 + k*IQR are outliers.
    More robust than stddev method as it's not affected by extreme values.

    Args:
        file_sizes: List of character counts for files in a category.
        iqr_multiplier: IQR multiplier for fences (1.5=mild, 3=extreme).

    Returns:
        Tuple of (lower_outlier_indices, upper_outlier_indices).
    """
    if len(file_sizes) < 4:
        # Need at least 4 points for meaningful quartiles
        return [], []

    # Get quartiles using Python stdlib (returns [Q1, Q2, Q3] for n=4)
    q1, _, q3 = quantiles(file_sizes, n=4)
    iqr = q3 - q1

    if iqr == 0:
        return [], []  # All files clustered, no outliers

    lower_fence = q1 - iqr_multiplier * iqr
    upper_fence = q3 + iqr_multiplier * iqr

    lower_outliers = [i for i, size in enumerate(file_sizes) if size < lower_fence]
    upper_outliers = [i for i, size in enumerate(file_sizes) if size > upper_fence]

    return lower_outliers, upper_outliers
