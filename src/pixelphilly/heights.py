"""Building height rule for the city's LI building footprints.

The footprint layer has two height fields, both in feet and both derived from
LiDAR by the city: `approx_hgt` (a rounded typical height) and `max_hgt` (the
highest return over the footprint). `max_hgt` can be thrown off by a taller
neighbor, a crane or a bad return: 1 Dock St, for example, reads 50 ft
approx vs. 369 ft max. So `approx_hgt` wins, `max_hgt` is the fallback, and a
fixed default is the last resort. Every fallback and conflict is reported
rather than silently fixed.
"""

FT_TO_M = 0.3048


def building_height(approx_hgt, max_hgt, default_m: float, outlier_ratio: float):
    """Return (height_m, source, is_outlier).

    source is "approx_hgt", "max_hgt" or "default". is_outlier flags records
    where max_hgt exceeds approx_hgt by more than `outlier_ratio` times.
    """
    approx = approx_hgt if approx_hgt and approx_hgt > 0 else None
    mx = max_hgt if max_hgt and max_hgt > 0 else None
    outlier = bool(approx and mx and mx > approx * outlier_ratio)
    if approx:
        return approx * FT_TO_M, "approx_hgt", outlier
    if mx:
        return mx * FT_TO_M, "max_hgt", outlier
    return default_m, "default", outlier
