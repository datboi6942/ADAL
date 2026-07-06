"""Tests for domain-specific validators."""


class TestAstrophysicsValidators:
    def test_kepler_third_law_earth(self):
        from adal.domains.astrophysics.validators import kepler_third_law

        a = kepler_third_law(365.25, 1.0)
        assert abs(a - 1.0) < 0.01

    def test_kepler_third_law_mercury(self):
        from adal.domains.astrophysics.validators import kepler_third_law

        a = kepler_third_law(88.0, 1.0)
        assert abs(a - 0.387) < 0.01

    def test_transit_depth_earth_sun(self):
        from adal.domains.astrophysics.constants import R_EARTH, R_SUN
        from adal.domains.astrophysics.validators import transit_depth

        depth = transit_depth(R_EARTH, R_SUN)
        assert abs(depth - 8.4e-5) < 1e-5

    def test_transit_depth_physical_valid(self):
        from adal.domains.astrophysics.validators import is_transit_depth_physical

        ok, _ = is_transit_depth_physical(0.01)
        assert ok

    def test_transit_depth_physical_too_deep(self):
        from adal.domains.astrophysics.validators import is_transit_depth_physical

        ok, _ = is_transit_depth_physical(0.5)
        assert not ok

    def test_stellar_mass_radius_valid(self):
        from adal.domains.astrophysics.validators import validate_stellar_mass_from_radius

        ok, _ = validate_stellar_mass_from_radius(1.0, 1.0)
        assert ok

    def test_stellar_mass_radius_invalid(self):
        from adal.domains.astrophysics.validators import validate_stellar_mass_from_radius

        ok, _ = validate_stellar_mass_from_radius(0.5, 5.0)
        assert not ok


class TestChemistryValidators:
    def test_thermodynamics_favorable(self):
        from adal.domains.chemistry.validators import validate_reaction_thermodynamics

        ok, msg, dg = validate_reaction_thermodynamics(-15.0, -30.0, 300)
        assert ok
        assert dg < 0

    def test_thermodynamics_unfavorable(self):
        from adal.domains.chemistry.validators import validate_reaction_thermodynamics

        ok, msg, dg = validate_reaction_thermodynamics(20.0, -50.0, 300)
        assert not ok
        assert dg > 0

    def test_activation_energy_surmountable(self):
        from adal.domains.chemistry.validators import validate_activation_energy

        ok, _ = validate_activation_energy(15.0, 358)
        assert ok

    def test_activation_energy_too_high(self):
        from adal.domains.chemistry.validators import validate_activation_energy

        ok, _ = validate_activation_energy(100.0, 298)
        assert not ok

    def test_activation_energy_negative(self):
        from adal.domains.chemistry.validators import validate_activation_energy

        ok, _ = validate_activation_energy(-5.0, 298)
        assert not ok

    def test_octet_rule_even(self):
        from adal.domains.chemistry.validators import validate_octet_rule

        ok, _ = validate_octet_rule(68)
        assert ok

    def test_octet_rule_odd(self):
        from adal.domains.chemistry.validators import validate_octet_rule

        ok, _ = validate_octet_rule(67)
        assert not ok

    def test_electronegativity_nonpolar(self):
        from adal.domains.chemistry.validators import validate_electronegativity_difference

        ok, _, bond_type = validate_electronegativity_difference("C", "H")
        assert ok
        assert bond_type == "non-polar_covalent"

    def test_electronegativity_ionic(self):
        from adal.domains.chemistry.validators import validate_electronegativity_difference

        ok, _, bond_type = validate_electronegativity_difference("Na", "Cl")
        assert ok
        assert bond_type == "ionic"

    def test_estimate_reaction_enthalpy(self):
        from adal.domains.chemistry.validators import estimate_reaction_enthalpy

        dh = estimate_reaction_enthalpy({"C-H": 1, "O-H": 1}, {"C-O": 1, "H-H": 1})
        expected = (413 + 467) - (358 + 436)
        assert abs(dh - expected) < 1.0

    def test_mol_weight_valid(self):
        from adal.domains.chemistry.validators import validate_mol_weight

        ok, _ = validate_mol_weight(180.16)
        assert ok

    def test_mol_weight_invalid(self):
        from adal.domains.chemistry.validators import validate_mol_weight

        ok, _ = validate_mol_weight(-5.0)
        assert not ok

    def test_ph_range_valid(self):
        from adal.domains.chemistry.validators import validate_ph_range

        ok, _ = validate_ph_range(7.0)
        assert ok


class TestPhysicsValidators:
    def test_energy_conservation(self):
        from adal.domains.physics.validators import validate_energy_conservation

        ok, _ = validate_energy_conservation(100.0, 100.0)
        assert ok

    def test_energy_not_conserved(self):
        from adal.domains.physics.validators import validate_energy_conservation

        ok, _ = validate_energy_conservation(100.0, 50.0)
        assert not ok

    def test_momentum_conservation(self):
        from adal.domains.physics.validators import validate_momentum_conservation

        ok, _ = validate_momentum_conservation([1.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        assert ok

    def test_ideal_gas_law(self):
        from adal.domains.physics.validators import validate_ideal_gas_law

        n, temp, vol = 1.0, 273.15, 0.022414
        pressure = n * 8.314 * temp / vol
        ok, _ = validate_ideal_gas_law(pressure, vol, n, temp)
        assert ok

    def test_de_broglie(self):
        import math

        from adal.domains.physics.constants import HBAR
        from adal.domains.physics.validators import validate_de_broglie_wavelength

        p = 1e-24
        lam = HBAR * 2 * math.pi / p
        ok, _ = validate_de_broglie_wavelength(p, lam)
        assert ok

    def test_relativistic_energy(self):
        from adal.domains.physics.constants import M_P, C
        from adal.domains.physics.validators import validate_relativistic_energy

        v = 0.9 * C
        import math
        gamma = 1.0 / math.sqrt(1 - 0.9**2)
        e = gamma * M_P * C**2
        ok, _ = validate_relativistic_energy(M_P, v, e)
        assert ok

    def test_doppler_shift_redshift(self):
        from adal.domains.physics.validators import validate_doppler_shift

        f0 = 5e14
        v = 3e7
        f_obs = f0 * (1 - v / 3e8)
        ok, _ = validate_doppler_shift(f0, f_obs, v)
        assert ok


class TestParticleNuclearValidators:
    def test_charge_conservation(self):
        from adal.domains.particle_nuclear.validators import validate_electric_charge_conservation

        ok, _ = validate_electric_charge_conservation([1.0, -1.0], [0.0])
        assert ok

    def test_charge_violation(self):
        from adal.domains.particle_nuclear.validators import validate_electric_charge_conservation

        ok, _ = validate_electric_charge_conservation([1.0], [0.0])
        assert not ok

    def test_baryon_conservation(self):
        from adal.domains.particle_nuclear.validators import validate_baryon_number_conservation

        ok, _ = validate_baryon_number_conservation(
            {"proton": 1, "neutron": 1},
            {"proton": 1, "neutron": 1},
        )
        assert ok

    def test_baryon_violation(self):
        from adal.domains.particle_nuclear.validators import validate_baryon_number_conservation

        ok, _ = validate_baryon_number_conservation(
            {"proton": 1},
            {"pion": 0},
        )
        assert not ok

    def test_lepton_conservation(self):
        from adal.domains.particle_nuclear.validators import validate_lepton_number_conservation

        ok, _ = validate_lepton_number_conservation(
            {"electron": 0},
            {"electron": -1, "electron_neutrino": 1},
        )
        assert ok

    def test_decay_kinematics_allowed(self):
        from adal.domains.particle_nuclear.validators import validate_decay_kinematics

        ok, _ = validate_decay_kinematics(139.57, [105.66, 0.0])
        assert ok

    def test_decay_kinematics_forbidden(self):
        from adal.domains.particle_nuclear.validators import validate_decay_kinematics

        ok, _ = validate_decay_kinematics(100.0, [120.0])
        assert not ok

    def test_two_body_decay_momentum(self):
        import math

        from adal.domains.particle_nuclear.validators import validate_two_body_decay_momentum

        parent_mass, daught1, daught2 = 139.57, 105.66, 0.0
        m2 = parent_mass**2
        dm_sum = (daught1 + daught2) ** 2
        dm_diff = (daught1 - daught2) ** 2
        p_star = math.sqrt((m2 - dm_sum) * (m2 - dm_diff)) / (2 * parent_mass)
        ok, _ = validate_two_body_decay_momentum(parent_mass, daught1, daught2, p_star)
        assert ok

    def test_binding_energy_fe56(self):
        from adal.domains.particle_nuclear.validators import validate_binding_energy

        ok, _ = validate_binding_energy(56, 26, 492.3)
        assert ok

    def test_binding_energy_invalid_a(self):
        from adal.domains.particle_nuclear.validators import validate_binding_energy

        ok, _ = validate_binding_energy(0, 0, 100)
        assert not ok
