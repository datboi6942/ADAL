"""Applied physics data fetchers."""

import structlog

logger = structlog.get_logger(__name__)


async def fetch_physical_constants() -> dict:
    """Fetch CODATA physical constants (simulated)."""
    script = '''
import json

constants = {
    "speed_of_light": 299792458,
    "planck_constant": 6.62607015e-34,
    "gravitational_constant": 6.67430e-11,
    "boltzmann_constant": 1.380649e-23,
    "elementary_charge": 1.602176634e-19,
    "electron_mass": 9.1093837015e-31,
    "proton_mass": 1.67262192369e-27,
    "fine_structure": 0.0072973525693,
    "stefan_boltzmann": 5.670374419e-8,
}
print(json.dumps(constants, indent=2))
'''
    return {"script": script, "description": "CODATA 2022 physical constants", "source": "simulated"}


async def fetch_spectral_line_data(element: str, ionization: int = 0) -> dict:
    """Fetch spectral line data for an element (NIST ASD simulated)."""
    script = f'''
import json

print(json.dumps({{
    "element": "{element}",
    "ionization": {ionization},
    "lines": [
        {{"wavelength_nm": 656.3, "transition": "3→2", "intensity": 1.00}},
        {{"wavelength_nm": 486.1, "transition": "4→2", "intensity": 0.47}},
        {{"wavelength_nm": 434.0, "transition": "5→2", "intensity": 0.26}},
    ],
    "source": "NIST ASD (simulated)"
}}, indent=2))
'''
    return {"script": script, "description": f"Spectral lines for {element} {ionization}+", "source": "simulated"}


async def fetch_thermodynamic_data(substance: str) -> dict:
    """Fetch thermodynamic data for a substance."""
    script = f'''
import json

print(json.dumps({{
    "substance": "{substance}",
    "H_f_kJ_per_mol": -285.8,
    "G_f_kJ_per_mol": -237.1,
    "S_J_per_mol_K": 70.0,
    "Cp_J_per_mol_K": 75.3,
    "source": "NIST Chemistry WebBook (simulated)",
}}, indent=2))
'''
    return {"script": script, "description": f"Thermodynamic data for {substance}", "source": "simulated"}
