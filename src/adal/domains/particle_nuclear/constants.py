C = 2.99792458e8
HBAR = 1.054571817e-34
HBAR_C = 197.3269804
M_E = 0.51099895000
M_MU = 105.6583755
M_TAU = 1776.86
M_PROTON = 938.27208816
M_NEUTRON = 939.56542052
M_PION = 139.57039
M_KAON = 493.677
M_W = 80377.0
M_Z = 91187.6
M_HIGGS = 125250.0

ALPHA_EM = 1.0 / 137.035999084
ALPHA_S_MZ = 0.1179
G_F = 1.1663787e-5
SIN2_THETA_W = 0.23121
V_UD = 0.974
V_US = 0.225
V_UB = 0.0035
V_CD = 0.225
V_CS = 0.974
V_CB = 0.041
V_TD = 0.0087
V_TS = 0.040
V_TB = 0.999

CKM_MATRIX = [
    [0.974, 0.225, 0.0035],
    [0.225, 0.974, 0.041],
    [0.0087, 0.040, 0.999],
]

QUARKS = {
    "u": {"charge": 2 / 3, "mass_mev": 2.16, "generation": 1},
    "d": {"charge": -1 / 3, "mass_mev": 4.67, "generation": 1},
    "c": {"charge": 2 / 3, "mass_mev": 1270, "generation": 2},
    "s": {"charge": -1 / 3, "mass_mev": 93, "generation": 2},
    "t": {"charge": 2 / 3, "mass_mev": 172760, "generation": 3},
    "b": {"charge": -1 / 3, "mass_mev": 4188, "generation": 3},
}

LEPTONS = {
    "e":  {"charge": -1, "mass_mev": 0.511, "lepton_number": 1},
    "νe": {"charge":  0, "mass_mev": 0,      "lepton_number": 1},
    "μ":  {"charge": -1, "mass_mev": 105.66, "lepton_number": 1},
    "νμ": {"charge":  0, "mass_mev": 0,      "lepton_number": 1},
    "τ":  {"charge": -1, "mass_mev": 1776.86, "lepton_number": 1},
    "ντ": {"charge":  0, "mass_mev": 0,      "lepton_number": 1},
}

CONSERVATION_LAWS = [
    "energy",
    "momentum",
    "angular_momentum",
    "electric_charge",
    "color_charge",
    "baryon_number",
    "lepton_number (per flavor)",
    "CPT",
]

NEUTRON_LIFETIME = 879.4
PROTON_LIFETIME_LOWER = 1.6e34

BINDING_ENERGY_PER_NUCLEON_FE = 8.79
BINDING_ENERGY_PER_NUCLEON_MAX = 8.79
