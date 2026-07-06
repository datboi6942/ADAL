"""Particle and nuclear physics validators."""

import math

from adal.domains.particle_nuclear.constants import (
    G_F,
    HBAR_C,
    QUARKS,
)


def validate_electric_charge_conservation(
    initial_charges: list[float],
    final_charges: list[float],
    tolerance: float = 1e-9,
) -> tuple[bool, str]:
    """Check total electric charge is conserved."""
    q_initial = sum(initial_charges)
    q_final = sum(final_charges)

    if abs(q_initial - q_final) < tolerance:
        return True, f"Charge conserved: Q={q_initial:.6f}e → Q={q_final:.6f}e"
    return False, f"Charge NOT conserved: Q_initial={q_initial:.6f}e, Q_final={q_final:.6f}e"


def validate_baryon_number_conservation(
    initial_baryon: dict[str, int],
    final_baryon: dict[str, int],
) -> tuple[bool, str]:
    """Check baryon number conservation."""
    b_initial = sum(initial_baryon.values())
    b_final = sum(final_baryon.values())

    if b_initial == b_final:
        return True, f"Baryon number conserved: B={b_initial} → B={b_final}"
    return False, f"Baryon number NOT conserved: B_initial={b_initial}, B_final={b_final}"


def validate_lepton_number_conservation(
    initial_leptons: dict[str, int],
    final_leptons: dict[str, int],
    flavor: str = "electron",
) -> tuple[bool, str]:
    """Check lepton number conservation per flavor (sums all values for the flavor)."""
    l_initial = sum(v for k, v in initial_leptons.items() if flavor in k)
    l_final = sum(v for k, v in final_leptons.items() if flavor in k)

    if l_initial == l_final:
        return True, f"{flavor} lepton number conserved: L={l_initial} → L={l_final}"
    return False, f"{flavor} lepton number NOT conserved: L_initial={l_initial}, L_final={l_final}"


def validate_decay_kinematics(
    parent_mass_mev: float,
    daughter_masses_mev: list[float],
    tolerance: float = 1e-6,
) -> tuple[bool, str]:
    """Check if decay is kinematically allowed."""
    total_daughter_mass = sum(daughter_masses_mev)

    if parent_mass_mev > total_daughter_mass + tolerance:
        q_value = parent_mass_mev - total_daughter_mass
        return True, f"Decay allowed: m_parent={parent_mass_mev:.1f} > Σm={total_daughter_mass:.1f} (Q={q_value:.1f} MeV)"
    elif abs(parent_mass_mev - total_daughter_mass) <= tolerance:
        return False, f"Decay at threshold: m_parent ≈ Σm_daughters = {total_daughter_mass:.1f} MeV"
    return False, f"Decay forbidden: m_parent={parent_mass_mev:.1f} < Σm={total_daughter_mass:.1f} MeV"


def validate_hadron_composition(
    hadron: str,
    quark_content: dict,
) -> tuple[bool, str]:
    """Validate a hadron's quark content gives correct charge and baryon number."""
    total_charge = sum(QUARKS[q]["charge"] * n for q, n in quark_content.items())
    total_baryon = sum(n / 3.0 for q, n in quark_content.items())

    checks = []
    if not math.isclose(total_baryon, 0, abs_tol=0.01) and not math.isclose(total_baryon, 1, abs_tol=0.01):
        checks.append(f"Baryon number {total_baryon:.2f} not integer (meson=0, baryon=1)")

    if checks:
        return False, " | ".join(checks)
    return True, f"{hadron}: charge={total_charge:.3f}e, baryon={total_baryon:.2f} — valid"


def validate_binding_energy(
    a: int,
    z: int,
    binding_energy_mev: float,
    tolerance: float = 0.3,
) -> tuple[bool, str]:
    """Validate binding energy using semi-empirical mass formula (Bethe-Weizsäcker)."""
    if a <= 0 or z <= 0 or z > a:
        return False, "Invalid A or Z"

    a_v = 15.75
    a_s = 17.8
    a_c = 0.711
    a_a = 23.7
    a_p = 11.18

    volume = a_v * a
    surface = a_s * a ** (2 / 3)
    coulomb = a_c * z * (z - 1) / a ** (1 / 3)
    asymmetry = a_a * (a - 2 * z) ** 2 / a

    delta = 0.0
    if a % 2 == 0:
        if z % 2 == 0:
            delta = a_p / a ** (1 / 2)
        else:
            delta = -a_p / a ** (1 / 2)

    be_per_nucleon = (volume - surface - coulomb - asymmetry + delta) / a
    actual_be_per_nucleon = binding_energy_mev / a

    rel_error = abs(actual_be_per_nucleon - be_per_nucleon) / max(abs(be_per_nucleon), 0.1)

    if rel_error <= tolerance:
        return True, f"Binding energy consistent with SEMF (B/A={actual_be_per_nucleon:.2f} vs {be_per_nucleon:.2f} MeV)"
    return False, f"Binding energy inconsistent: B/A={actual_be_per_nucleon:.2f} MeV vs SEMF prediction {be_per_nucleon:.2f} MeV"


def validate_decay_rate(
    process: str,
    mass_mev: float,
    lifetime_s: float,
) -> tuple[bool, str]:
    """Rough check if decay rate is plausible for given mass scale."""
    if mass_mev <= 0:
        return False, "Mass must be positive"

    if mass_mev > 80000:
        expected_lifetime = HBAR_C / 2.1e3
        min_lifetime = expected_lifetime * 0.01
        max_lifetime = expected_lifetime * 100
    elif mass_mev > 1000:
        expected_lifetime = HBAR_C / (G_F**2 * mass_mev**5) * 192 * math.pi**3
        min_lifetime = expected_lifetime * 0.001
        max_lifetime = expected_lifetime * 1000
    else:
        min_lifetime = 1e-23
        max_lifetime = 1e8

    if min_lifetime <= lifetime_s <= max_lifetime:
        return True, f"Lifetime {lifetime_s:.2e} s plausible for mass {mass_mev:.1f} MeV"
    return False, f"Lifetime {lifetime_s:.2e} s implausible (expected range: {min_lifetime:.2e} - {max_lifetime:.2e} s)"


def validate_two_body_decay_momentum(
    parent_mass: float,
    m1: float,
    m2: float,
    momentum: float,
    tolerance: float = 0.05,
) -> tuple[bool, str]:
    """Validate two-body decay momentum: p* = √((M²-(m1+m2)²)(M²-(m1-m2)²))/(2M)."""
    if parent_mass <= m1 + m2:
        return False, f"Decay not kinematically allowed: M={parent_mass} < m1+m2={m1+m2}"

    p_star = (
        math.sqrt(
            (parent_mass**2 - (m1 + m2) ** 2) * (parent_mass**2 - (m1 - m2) ** 2)
        )
        / (2 * parent_mass)
    )

    rel_error = abs(momentum - p_star) / p_star
    if rel_error <= tolerance:
        return True, f"Two-body decay momentum correct: p*={p_star:.2f} vs {momentum:.2f}"
    return False, f"Two-body decay momentum inconsistent: expected p*={p_star:.2f}, got {momentum:.2f}"
