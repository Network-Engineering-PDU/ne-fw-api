"""Shared input power/phase correction for API and PMB."""
import math


def normalize_phase_vi(ph: float) -> float:
    """Wrap to [-180, 180] and fix CT polarity inversion (|angle| > 90°)."""
    if ph > 180.0:
        ph -= 360.0
    elif ph < -180.0:
        ph += 360.0
    if abs(ph) > 90.0:
        ph = ph - 180.0 if ph > 0 else ph + 180.0
    return ph


def correct_input_measurements(
    voltage: float,
    current: float,
    phase: float,
    active_power: float,
    reactive_power: float,
    apparent_power: float,
    power_factor: float,
    energy: float,
):
    """
    Recompute P/Q/S/PF from V,I and corrected phase; ensure P, PF, E are positive.
    Matches web UI logic in ne/app/views.py.
    """
    phase = normalize_phase_vi(phase)

    if voltage and current:
        ph_rad = math.radians(phase)
        active_power = voltage * current * math.cos(ph_rad)
        reactive_power = voltage * current * math.sin(ph_rad)
        apparent_power = voltage * current
        power_factor = math.cos(ph_rad)

    active_power = abs(active_power)
    power_factor = abs(power_factor)
    energy = abs(energy)

    return (
        voltage,
        current,
        active_power,
        reactive_power,
        apparent_power,
        power_factor,
        phase,
        energy,
    )
