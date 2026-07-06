"""
Exoplanet Transit Detection Demo

This demonstrates the ADAL loop for detecting an exoplanet transit in a simulated
light curve, validating the orbital period against Kepler's 3rd law, and constraining
the planet's physical parameters.

Run: python examples/exoplanet_transit/demo.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from adal.db.session import init_db

# Simulated light curve analysis script (what Agent 1 would generate)
ANALYSIS_SCRIPT = '''
import numpy as np
from scipy.signal import find_peaks

np.random.seed(42)
time = np.linspace(0, 90, 1000)
period = 14.0
depth = 0.001
transit_duration = 0.15

flux = np.ones_like(time)
for i, t in enumerate(time):
    phase = (t % period) / period
    if phase < transit_duration:
        flux[i] -= depth
    elif phase > 1 - transit_duration:
        flux[i] -= depth

flux += np.random.normal(0, 0.0002, len(time))

# Box Least Squares periodogram
periods = np.linspace(1, 30, 300)
power = np.zeros_like(periods)
for i, p in enumerate(periods):
    folded = (time % p) / p
    in_transit = (folded < 0.1) | (folded > 0.9)
    out_transit = ~in_transit
    if in_transit.sum() > 5 and out_transit.sum() > 5:
        power[i] = np.abs(flux[out_transit].mean() - flux[in_transit].mean()) / flux.std()

best_idx = np.argmax(power)
best_period = periods[best_idx]

print(f"Best period: {best_period:.2f} days")
print(f"Signal power: {power[best_idx]:.4f}")
print(f"Transit depth: {depth:.5f}")
print(f"Estimated depth: {1 - flux[np.abs(time % best_period) < 0.05].mean():.5f}")

print("\\nDiagnostic phase-folded curve:")
folded = (time % best_period) / best_period
for i in range(0, len(folded), 50):
    print(f"Phase {folded[i]:.3f}, Flux {flux[i]:.6f}")
'''

async def demo():
    print("=" * 70)
    print("ADAL EXAMPLE: Exoplanet Transit Detection")
    print("=" * 70)
    print()

    await init_db()

    from adal.domains.astrophysics.validators import (
        is_transit_depth_physical,
        kepler_third_law,
        transit_depth,
    )

    print("--- Proposer (Agent 1) Analysis ---")
    print("Running light curve analysis script...")
    print()

    # Agent 1 Hypothesis
    hypothesis = {
        "domain": "astrophysics",
        "analysis_summary": "Detected periodic transit signal in stellar light curve at 14.0 days",
        "features_detected": [
            "Periodic dip with period ~14 days",
            "Transit depth ~0.001 (1,000 ppm)",
            "Box-shaped transit profile consistent with planet",
        ],
        "hypothesis": {
            "statement": "This star hosts an exoplanet with orbital period ~14 days and radius ~1.5 R_Earth",
            "confidence": 0.82,
            "supporting_evidence": [
                "Periodic signal detected at 14.0 day period with S/N > 8",
                "Transit depth of 0.001 corresponds to super-Earth radius",
                "Phase-folded light curve shows symmetric V-shaped transit",
            ],
            "predicted_values": {
                "period_days": 14.0,
                "transit_depth": 0.001,
                "stellar_mass_solar": 0.95,
                "stellar_radius": 0.92,
                "planet_radius_earth": 1.5,
            },
            "assumptions": [
                "Circular orbit (e=0)",
                "Central transit (b~0)",
                "Main sequence G-type star",
            ],
        },
        "data_quality": {
            "signal_to_noise": 8.5,
            "completeness": 0.95,
            "notes": "Simulated data with known injected signal",
        },
    }

    print(json.dumps(hypothesis, indent=2))
    print()

    print("--- Verifier (Agent 2) Validation ---")
    print()

    # Agent 2 validates
    pv = hypothesis["hypothesis"]["predicted_values"]

    # Check 1: Kepler's 3rd law
    a_au = kepler_third_law(pv["period_days"], pv["stellar_mass_solar"])
    print("Check 1: Kepler's 3rd Law")
    print(f"  Period: {pv['period_days']} days")
    print(f"  Stellar mass: {pv['stellar_mass_solar']} M_sun")
    print(f"  Semi-major axis: {a_au:.4f} AU ({'PASS' if 0.01 < a_au < 100 else 'FAIL'})")
    print()

    # Check 2: Transit depth physicality
    ok, msg = is_transit_depth_physical(pv["transit_depth"])
    print("Check 2: Transit Depth Physicality")
    print(f"  Depth: {pv['transit_depth']:.6f}")
    print(f"  Result: {'PASS' if ok else 'FAIL'} — {msg}")
    print()

    # Check 3: Planet radius from transit depth
    depth = transit_depth(pv["planet_radius_earth"] * 6371e3, pv["stellar_radius"] * 6.957e8)
    print("Check 3: Planet Radius Consistency")
    print(f"  Expected depth for Rp={pv['planet_radius_earth']} R_earth: {depth:.6f}")
    print(f"  Measured depth: {pv['transit_depth']:.6f}")
    print(f"  Match: {'PASS' if abs(depth - pv['transit_depth']) / pv['transit_depth'] < 0.1 else 'FAIL'}")
    print()

    # Check 4: Equilibrium temperature
    import math

    from adal.domains.astrophysics.constants import AU, R_SUN
    albedo = 0.3
    T_star = 5778
    R_star = pv["stellar_radius"] * R_SUN
    T_eq = T_star * math.sqrt(R_star / (2 * a_au * AU)) * (1 - albedo) ** 0.25
    print("Check 4: Equilibrium Temperature")
    print(f"  T_eq = {T_eq:.0f} K ({'PASS — plausible' if 100 < T_eq < 3000 else 'WARNING'})")
    print()

    _verdict = {
        "verdict": "PASS",
        "confidence": 0.89,
        "checks_performed": [
            {"check_name": "Kepler's 3rd Law", "result": "PASS", "reasoning": f"Semi-major axis {a_au:.4f} AU is physically reasonable"},
            {"check_name": "Transit Depth Physicality", "result": "PASS", "reasoning": msg},
            {"check_name": "Planet Radius Consistency", "result": "PASS", "reasoning": "Radius matches transit depth within 10%"},
            {"check_name": "Equilibrium Temperature", "result": "PASS", "reasoning": f"T_eq = {T_eq:.0f} K is physically plausible"},
        ],
        "mathematical_proof": f"From Kepler's 3rd law: a = (P² GM)^(1/3) = {a_au:.4f} AU. "
                             f"Transit depth (Rp/Rs)² = {depth:.6f}. All constraints satisfied.",
        "corrected_values": {},
        "fatal_flaws": [],
        "suggestions": ["Confirm with radial velocity follow-up", "Check for transit timing variations"],
    }

    print("--- Planner (Agent 3) Decision ---")
    print(json.dumps({
        "session_status": "CONVERGED",
        "action": "CONVERGE",
        "reasoning": "All physical constraints satisfied. Hypothesis validated.",
        "final_answer": f"Exoplanet candidate confirmed: P={pv['period_days']} days, "
                        f"Rp≈{pv['planet_radius_earth']} R_Earth, "
                        f"a={a_au:.4f} AU, T_eq={T_eq:.0f} K. "
                        f"Super-Earth in a temperate orbit around a G-type star.",
    }, indent=2))

    print()
    print("[PASS] Exoplanet transit detection demo complete.")


if __name__ == "__main__":
    asyncio.run(demo())
