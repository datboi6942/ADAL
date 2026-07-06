"""Chemistry data fetchers from PubChem and other public databases."""

import structlog

logger = structlog.get_logger(__name__)


async def fetch_pubchem_data(compound_name: str) -> dict:
    """Fetch molecular data from PubChem."""

    script = f'''
import json

compound = "{compound_name}"
data = {{
    "source": "PubChem (simulated)",
    "compound": compound,
    "molecular_weight": 180.16,
    "molecular_formula": "C9H8O4",
    "iupac_name": "2-acetoxybenzoic acid",
    "smiles": "CC(=O)OC1=CC=CC=C1C(=O)O",
    "logp": 1.19,
    "h_bond_donors": 1,
    "h_bond_acceptors": 4,
    "rotatable_bonds": 3,
    "tpsa": 63.6,
}}
print(json.dumps(data, indent=2))
'''
    return {
        "script": script,
        "description": f"PubChem data for {compound_name}",
        "source": "pubchem_simulated",
    }


async def fetch_reaction_data(reaction_smiles: str) -> dict:
    """Fetch reaction data from chemical databases."""

    script = f'''
import json

print(json.dumps({{
    "reaction": "{reaction_smiles}",
    "catalyst": "H2SO4 (conc.)",
    "temperature": "60-80 °C",
    "solvent": "acetic anhydride",
    "yield": "85-90%",
    "hazards": ["corrosive", "flammable"],
    "byproducts": ["acetic acid"],
}}, indent=2))
'''
    return {
        "script": script,
        "description": f"Reaction data for {reaction_smiles}",
        "source": "simulated",
    }


async def fetch_spectral_data(compound_smiles: str, technique: str = "NMR") -> dict:
    """Fetch predicted spectral data."""

    script = f'''
import json

print(json.dumps({{
    "compound": "{compound_smiles}",
    "technique": "{technique}",
    "predicted_shifts": {{
        "1H": ["2.3 (s, 3H, CH3)", "7.1-8.1 (m, 4H, Ar-H)", "12.0 (br, 1H, COOH)"],
        "13C": ["21.0 (CH3)", "123-135 (Ar-C)", "170.0 (C=O ester)", "172.5 (C=O acid)"],
    }},
    "notes": "Predicted shifts (simulated)",
}}, indent=2))
'''
    return {
        "script": script,
        "description": f"{technique} spectral prediction for {compound_smiles}",
        "source": "predicted",
    }
