"""Applied physics validators: conservation laws, thermodynamics, mechanics."""

import math

from adal.domains.physics.constants import (
    HBAR,
    K_B,
    R_GAS,
    SIGMA_SB,
    C,
    G,
)


def validate_energy_conservation(
    e_initial: float,
    e_final: float,
    tolerance: float = 1e-6,
) -> tuple[bool, str]:
    """Validate energy conservation: E_initial should equal E_final within tolerance."""
    if e_initial <= 0 and e_final <= 0:
        return False, "Energies must be positive"

    relative_error = abs(e_initial - e_final) / max(abs(e_initial), abs(e_final), 1e-30)
    if relative_error <= tolerance:
        return True, f"Energy conserved (ΔE/E = {relative_error:.2e})"
    return False, f"Energy not conserved: E_initial={e_initial:.4f}, E_final={e_final:.4f} (error: {relative_error:.2e})"


def validate_momentum_conservation(
    p_initial: list[float],
    p_final: list[float],
    tolerance: float = 1e-6,
) -> tuple[bool, str]:
    """Validate momentum conservation in 3D."""
    if len(p_initial) != 3 or len(p_final) != 3:
        return False, "Momentum vectors must be 3D"

    diff = [abs(p_initial[i] - p_final[i]) for i in range(3)]
    mag_initial = math.sqrt(sum(x**2 for x in p_initial))
    mag_diff = math.sqrt(sum(x**2 for x in diff))

    if mag_initial == 0 and mag_diff == 0:
        return True, "Momentum conserved (zero initial/final)"

    relative_error = mag_diff / max(mag_initial, 1e-30)
    if relative_error <= tolerance:
        return True, f"Momentum conserved (Δp/p = {relative_error:.2e})"
    return False, f"Momentum not conserved (Δp = {mag_diff:.4f}, relative: {relative_error:.2e})"


def validate_stefan_boltzmann(
    temperature_k: float,
    radius_m: float,
    luminosity_w: float,
    emissivity: float = 1.0,
    tolerance: float = 0.1,
) -> tuple[bool, str]:
    """Validate luminosity matches Stefan-Boltzmann law: L = 4πR²εσT⁴."""
    if temperature_k <= 0:
        return False, "Temperature must be positive"

    expected_l = 4 * math.pi * radius_m**2 * emissivity * SIGMA_SB * temperature_k**4
    rel_error = abs(luminosity_w - expected_l) / max(expected_l, 1e-30)

    if rel_error <= tolerance:
        return True, f"Luminosity consistent with Stefan-Boltzmann (error: {rel_error:.2e})"
    return False, f"Luminosity inconsistent: expected {expected_l:.2e} W, got {luminosity_w:.2e} W"


def validate_ideal_gas_law(
    pressure_pa: float,
    volume_m3: float,
    n_moles: float,
    temperature_k: float,
    tolerance: float = 0.05,
) -> tuple[bool, str]:
    """Validate PV = nRT for ideal gas."""
    if temperature_k <= 0:
        return False, "Temperature must be > 0 K"
    if volume_m3 <= 0:
        return False, "Volume must be > 0 m^3"

    expected_p = n_moles * R_GAS * temperature_k / volume_m3
    rel_error = abs(pressure_pa - expected_p) / max(expected_p, 1e-30)

    if rel_error <= tolerance:
        return True, f"Ideal gas law holds (error: {rel_error:.2e})"
    return False, f"Ideal gas law violated: P_expected={expected_p:.1f} Pa, P_actual={pressure_pa:.1f} Pa"


def validate_gravitational_binding_energy(
    mass_kg: float,
    radius_m: float,
    binding_energy_j: float,
    tolerance: float = 0.1,
) -> tuple[bool, str]:
    """Validate gravitational binding energy ~ 3GM²/5R for a uniform sphere."""
    if radius_m <= 0:
        return False, "Radius must be positive"

    expected = (3 * G * mass_kg**2) / (5 * radius_m)
    rel_error = abs(binding_energy_j - expected) / max(abs(expected), 1e-30)

    if rel_error <= tolerance:
        return True, f"Binding energy consistent (error: {rel_error:.2e})"
    return False, f"Binding energy inconsistent: expected {expected:.2e} J, got {binding_energy_j:.2e} J"


def validate_de_broglie_wavelength(
    momentum: float,
    wavelength: float,
    tolerance: float = 0.05,
) -> tuple[bool, str]:
    """Validate λ = h/p (de Broglie)."""
    if momentum <= 0:
        return False, "Momentum must be positive"

    expected_lambda = HBAR * 2 * math.pi / momentum
    rel_error = abs(wavelength - expected_lambda) / expected_lambda

    if rel_error <= tolerance:
        return True, f"De Broglie wavelength consistent (error: {rel_error:.2e})"
    return False, f"De Broglie violated: expected λ={expected_lambda:.4e} m, got λ={wavelength:.4e} m"


def validate_thermal_velocity(
    temperature_k: float,
    mass_kg: float,
    velocity_ms: float,
    tolerance: float = 0.2,
) -> tuple[bool, str]:
    """Validate v ≈ sqrt(3kT/m) for an ideal gas particle."""
    if temperature_k <= 0 or mass_kg <= 0:
        return False, "Temperature and mass must be positive"

    v_rms = math.sqrt(3 * K_B * temperature_k / mass_kg)
    rel_error = abs(velocity_ms - v_rms) / v_rms

    if rel_error <= tolerance:
        return True, f"Thermal velocity consistent (v_rms={v_rms:.1f} m/s, given={velocity_ms:.1f} m/s)"
    return False, f"Thermal velocity inconsistent: v_rms={v_rms:.1f} m/s, given={velocity_ms:.1f} m/s"


def validate_relativistic_energy(
    mass_kg: float,
    velocity_ms: float,
    energy_j: float,
    tolerance: float = 0.05,
) -> tuple[bool, str]:
    """Validate relativistic energy E = γmc²."""
    if abs(velocity_ms) >= C:
        return False, f"Velocity ({velocity_ms:.2e} m/s) exceeds speed of light"

    gamma = 1.0 / math.sqrt(1.0 - (velocity_ms**2 / C**2))
    expected_e = gamma * mass_kg * C**2
    rel_error = abs(energy_j - expected_e) / expected_e

    if rel_error <= tolerance:
        return True, f"Relativistic energy consistent (γ={gamma:.4f})"
    return False, f"Relativistic energy violated: expected {expected_e:.4e} J, got {energy_j:.4e} J"


def validate_doppler_shift(
    emitted_freq: float,
    observed_freq: float,
    radial_velocity_ms: float,
    tolerance: float = 0.05,
) -> tuple[bool, str]:
    """Validate observed frequency matches Doppler shift for given radial velocity."""
    if emitted_freq <= 0:
        return False, "Emitted frequency must be positive"

    expected = emitted_freq * (1.0 - radial_velocity_ms / C)
    rel_error = abs(observed_freq - expected) / expected

    if rel_error <= tolerance:
        return True, f"Doppler shift consistent (error: {rel_error:.2e})"
    return False, f"Doppler shift inconsistent: expected f={expected:.4e} Hz, got f={observed_freq:.4e} Hz"
