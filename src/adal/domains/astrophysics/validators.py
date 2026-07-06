import math

from adal.domains.astrophysics.constants import (
    DAY_SECONDS,
    M_EARTH,
    M_JUPITER,
    R_JUPITER,
    R_SUN,
    YEAR_SECONDS,
    G,
)


def kepler_third_law(period_days: float, stellar_mass_solar: float) -> float:
    """Calculate semi-major axis in AU from orbital period and stellar mass."""
    period_seconds = period_days * DAY_SECONDS
    period_years = period_seconds / YEAR_SECONDS
    a_au = (period_years**2 * stellar_mass_solar) ** (1 / 3)
    return a_au


def calculate_orbital_period(semi_major_axis_au: float, stellar_mass_solar: float) -> float:
    """Calculate orbital period in days from semi-major axis and stellar mass."""
    period_years = math.sqrt(semi_major_axis_au**3 / stellar_mass_solar)
    return period_years * 365.25


def transit_depth(planet_radius: float, star_radius: float) -> float:
    """Calculate expected transit depth (relative flux drop)."""
    return (planet_radius / star_radius) ** 2


def is_transit_depth_physical(depth: float, star_radius: float = R_SUN) -> tuple[bool, str]:
    """Check if transit depth is physically plausible for any planet size."""
    min_planet = 0.1 * M_EARTH / M_JUPITER * R_JUPITER
    max_planet = 2.5 * R_JUPITER
    min_depth = (min_planet / star_radius) ** 2
    max_depth = (max_planet / star_radius) ** 2

    if depth < min_depth:
        return False, f"Transit depth {depth:.2e} is below minimum detectability ({min_depth:.2e})"
    if depth > max_depth:
        return False, f"Transit depth {depth:.2e} exceeds maximum for a planet ({max_depth:.2e})"
    return True, "Transit depth is within physical bounds"


def stellar_density_from_transit(
    period_days: float, impact_param: float, duration_hours: float, eccentricity: float = 0
) -> float:
    """Estimate stellar density from transit parameters (kg/m^3)."""
    period_seconds = period_days * DAY_SECONDS
    duration = duration_hours * 3600
    denom = (duration * 0.5) ** 2
    if denom == 0:
        return float("inf")
    rho = (3 * math.pi / (G * period_seconds**2)) * ((1 - impact_param**2) / denom) ** (3 / 2)
    rho *= (1 + eccentricity) / (1 - eccentricity) if eccentricity > 0 else 1.0
    return rho


def validate_orbital_resonance(periods: list[float], tolerance: float = 0.02) -> list[tuple[int, int, float]]:
    """Check for orbital resonances in a list of periods. Returns [(ratio_num, ratio_denom, error)]."""
    resonances = []
    for i in range(len(periods)):
        for j in range(i + 1, len(periods)):
            ratio = periods[j] / periods[i] if periods[i] > 0 else float("inf")
            for num in range(1, 6):
                for denom in range(1, 6):
                    expected = num / denom
                    error = abs(ratio - expected) / expected
                    if error < tolerance and num != denom:
                        resonances.append((num, denom, error))
    return resonances


def validate_habitable_zone(semi_major_axis_au: float, stellar_luminosity_solar: float) -> tuple[bool, str]:
    """Check if a planet is in the conservative habitable zone."""
    inner = 0.95 * math.sqrt(stellar_luminosity_solar)
    outer = 1.67 * math.sqrt(stellar_luminosity_solar)

    if inner <= semi_major_axis_au <= outer:
        return True, f"Planet at {semi_major_axis_au:.3f} AU is in the HZ ({inner:.3f} - {outer:.3f} AU)"
    elif semi_major_axis_au < inner:
        return False, f"Planet at {semi_major_axis_au:.3f} AU is interior to the HZ (inner edge: {inner:.3f} AU)"
    else:
        return False, f"Planet at {semi_major_axis_au:.3f} AU is exterior to the HZ (outer edge: {outer:.3f} AU)"


def validate_stellar_mass_from_radius(stellar_mass: float, stellar_radius: float) -> tuple[bool, str]:
    """Validate that a main-sequence star's mass-radius relation is plausible."""
    if stellar_mass <= 0:
        return False, "Stellar mass must be positive"

    if stellar_mass < 1.0:
        expected_radius = stellar_mass**0.8
    else:
        expected_radius = stellar_mass**0.57

    ratio = stellar_radius / expected_radius
    if 0.3 < ratio < 3.0:
        return True, f"Mass-radius relation plausible (ratio: {ratio:.2f})"
    return False, f"Mass-radius relation implausible: expected R ~ {expected_radius:.2f} Rsun, got {stellar_radius:.2f} Rsun"
