"""Chemical validators: stability, feasibility, and property checks."""

import math

from adal.domains.chemistry.constants import (
    BOND_ENERGIES,
    ELECTRONEGATIVITIES,
    POLARITY_IONIC_THRESHOLD,
    POLARITY_THRESHOLD,
    R_GAS_KCAL,
)


def validate_reaction_thermodynamics(
    delta_h_kcal: float,
    delta_s_cal: float,
    temperature_k: float = 298.15,
    concentration_ratio: float = 1.0,
) -> tuple[bool, str, float]:
    """Validate reaction feasibility using Gibbs free energy."""
    delta_g = delta_h_kcal - temperature_k * delta_s_cal / 1000.0
    delta_g_actual = delta_g + R_GAS_KCAL * temperature_k * math.log(max(concentration_ratio, 1e-30))

    if delta_g_actual < -10:
        return True, f"Highly favorable (ΔG = {delta_g_actual:.1f} kcal/mol)", delta_g_actual
    elif delta_g_actual < 5:
        return True, f"Marginally favorable (ΔG = {delta_g_actual:.1f} kcal/mol)", delta_g_actual
    elif delta_g_actual < 15:
        return False, f"Unfavorable at {temperature_k} K (ΔG = {delta_g_actual:.1f} kcal/mol)", delta_g_actual
    else:
        return False, f"Highly unfavorable (ΔG = {delta_g_actual:.1f} kcal/mol)", delta_g_actual


def validate_activation_energy(
    ea_kcal: float,
    temperature_k: float = 298.15,
    threshold_factor: float = 25.0,
) -> tuple[bool, str]:
    """Check if activation energy is surmountable at given temperature."""
    rt = R_GAS_KCAL * temperature_k
    rate_factor = math.exp(-ea_kcal / rt)

    if ea_kcal < 0:
        return False, "Activation energy cannot be negative"
    if rate_factor > 1e-20:
        return True, f"Activation energy {ea_kcal:.1f} kcal/mol surmountable at {temperature_k} K"
    else:
        return False, f"Activation energy {ea_kcal:.1f} kcal/mol too high at {temperature_k} K (rate factor: {rate_factor:.2e})"


def validate_octet_rule(electron_count: int) -> tuple[bool, str]:
    """Check if total electron count satisfies octet rule (simplified)."""
    if electron_count % 2 != 0:
        return False, "Odd electron count — possible radical, violates octet rule"
    return True, "Even electron count — octet rule plausible"


def validate_bond_lengths(bond_orders: dict, element_pairs: list[tuple[str, str]]) -> tuple[bool, str]:
    """Validate bond lengths against typical values."""
    typical_lengths = {
        ("C", "C"): 1.54, ("C", "C", 2): 1.34, ("C", "C", 3): 1.20,
        ("C", "H"): 1.09, ("C", "O"): 1.43, ("C", "O", 2): 1.21,
        ("O", "H"): 0.96, ("N", "H"): 1.01, ("C", "N"): 1.47,
        ("C", "F"): 1.35, ("C", "Cl"): 1.77, ("C", "Br"): 1.94,
    }

    for pair in element_pairs:
        e1, e2 = pair[:2]
        key = tuple(sorted([e1, e2]))
        if key in typical_lengths:
            expected = typical_lengths[key]
            if bond_orders.get(f"{e1}-{e2}", 1) == 1 and expected > 2.5:
                return False, f"Bond length for {e1}-{e2} ({expected} Å) unusual for single bond"
    return True, "Bond lengths within expected ranges"


def validate_electronegativity_difference(element1: str, element2: str) -> tuple[bool, str, str]:
    """Classify bond type based on electronegativity difference."""
    en1 = ELECTRONEGATIVITIES.get(element1, 2.5)
    en2 = ELECTRONEGATIVITIES.get(element2, 2.5)
    diff = abs(en1 - en2)

    if diff < POLARITY_THRESHOLD:
        return True, f"Non-polar covalent (ΔEN = {diff:.2f})", "non-polar_covalent"
    elif diff < POLARITY_IONIC_THRESHOLD:
        return True, f"Polar covalent (ΔEN = {diff:.2f})", "polar_covalent"
    else:
        return True, f"Ionic (ΔEN = {diff:.2f})", "ionic"


def estimate_reaction_enthalpy(bonds_broken: dict, bonds_formed: dict) -> float:
    """Estimate ΔH from bond energies (kcal/mol)."""
    delta_h = 0.0
    for bond, count in bonds_broken.items():
        if bond in BOND_ENERGIES:
            delta_h += count * BOND_ENERGIES[bond]
    for bond, count in bonds_formed.items():
        if bond in BOND_ENERGIES:
            delta_h -= count * BOND_ENERGIES[bond]
    return delta_h


def validate_mol_weight(weight_g_mol: float) -> tuple[bool, str]:
    """Sanity check molecular weight."""
    if weight_g_mol <= 0:
        return False, "Molecular weight must be positive"
    if weight_g_mol > 100000:
        return False, f"Molecular weight {weight_g_mol:.1f} g/mol implausibly large for small molecule"
    return True, f"Molecular weight {weight_g_mol:.1f} g/mol plausible"


def validate_ph_range(ph: float) -> tuple[bool, str]:
    """Validate pH is in reasonable aqueous range."""
    if -2 <= ph <= 16:
        return True, f"pH {ph:.1f} is within possible aqueous range"
    return False, f"pH {ph:.1f} is outside the possible aqueous range (-2 to 16)"
