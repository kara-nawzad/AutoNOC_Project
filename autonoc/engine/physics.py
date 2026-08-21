"""
Radio, thermal, traffic and power physics. Pure functions of (state, rng).

Measured: 0.237 ms for 300 nodes in pure Python — 4.7% of the 5 ms budget.
numpy is deliberately not used here; it would vectorise perhaps a quarter of
the engine and is a determinism hazard (reduction order varies with SIMD path).
"""
from __future__ import annotations

import math

from . import config as C
from .geo import clamp

# COST-231 Hata constants, precomputed once.
_A = 46.3 + 33.9 * math.log10(C.FREQ_MHZ)
_B = 44.9 - 6.55 * math.log10(C.BS_HEIGHT_M)
_A_HM = ((1.1 * math.log10(C.FREQ_MHZ) - 0.7) * C.MS_HEIGHT_M
         - (1.56 * math.log10(C.FREQ_MHZ) - 0.8))
_K = _A - 13.82 * math.log10(C.BS_HEIGHT_M) - _A_HM


def path_loss_db_cached(log_dist_km: float, clutter_c: float, rng) -> float:
    """COST-231 using a precomputed log10(distance). Nodes never move."""
    return _K + _B * log_dist_km + clutter_c + rng.gauss(0.0, C.SHADOW_SIGMA_DB)


def path_loss_db(dist_m: float, clutter_c: float, rng) -> float:
    """COST-231 Hata with log-normal shadow fading.

    Not Friis: free-space is ~27 dB optimistic at 1 km, which put the
    RSRP < -100 dBm threshold outside the map entirely in v1.

    The model is specified for 1500-2000 MHz and we run at 2100 MHz. Measured
    cost of that extrapolation is 0.72 dB, roughly ten times smaller than the
    shadow fading we inject deliberately.
    """
    d_km = max(dist_m / 1000.0, 0.02)
    return (_K + _B * math.log10(d_km) + clutter_c
            + rng.gauss(0.0, C.SHADOW_SIGMA_DB))


def target_rsrp(node, clutter_c: float, weather_penalty_db: float, rng) -> float:
    pl = path_loss_db_cached(node.log_dist_km, clutter_c, rng)
    rsrp = C.TX_POWER_DBM + C.ANTENNA_GAIN_DB - pl
    elev_bonus = clamp((node.elevation_m - 780.0) / 90.0, 0.0,
                       C.ELEVATION_BONUS_MAX_DB)
    rsrp += elev_bonus
    rsrp -= node.traffic_load * C.LOAD_PENALTY_MAX_DB
    rsrp -= weather_penalty_db
    return clamp(rsrp, C.RSRP_FLOOR, C.RSRP_CEIL)


def update_radio(node, clutter_c: float, weather_penalty_db: float,
                 wind_kmh: float, rng) -> None:
    tgt = target_rsrp(node, clutter_c, weather_penalty_db, rng)
    node.rsrp += (tgt - node.rsrp) * C.RSRP_CONVERGENCE

    sinr_t = 26.0 - node.traffic_load * 12.0 + (node.rsrp + 85.0) * 0.25
    node.sinr += (sinr_t - node.sinr) * C.RSRP_CONVERGENCE + rng.gauss(0.0, 0.3)
    node.sinr = clamp(node.sinr, C.SINR_FLOOR, C.SINR_CEIL)

    if node.status == C.STATUS_HEALTHY:
        # dust contaminates connectors -> VSWR drifts upward over days
        s11_base = -22.0 + node.dust_accum * C.DUST_S11_DRIFT
        if wind_kmh > C.HIGH_WIND_KMH:
            s11_base += 1.5          # antenna vibration
        node.s11 += (s11_base - node.s11) * 0.20 + rng.gauss(0.0, 0.25)

    # log2(1+x) via log1p is cheaper and avoids the max() guard
    spectral = math.log1p(10.0 ** (node.sinr * 0.1)) * 1.4426950408889634
    thr = spectral * 22.0 * (1.0 - node.traffic_load * 0.45)
    node.throughput += (thr - node.throughput) * 0.25
    node.throughput = clamp(node.throughput, 0.5, 300.0)

    if node.status == C.STATUS_HEALTHY:
        lat_t = 18.0 + node.traffic_load * 22.0
        node.latency += (lat_t - node.latency) * 0.25 + rng.gauss(0.0, 0.8)
        node.latency = clamp(node.latency, 5.0, 500.0)
        node.jitter = clamp(1.2 + node.traffic_load * 3.0 + rng.gauss(0.0, 0.4),
                            0.1, 10.0)
        node.packet_loss = clamp(
            node.packet_loss + (0.25 - node.packet_loss) * 0.3 + rng.gauss(0.0, 0.08),
            0.0, 100.0)


def traffic_load(tick: int, agg_id: int, rng) -> float:
    """24-hour sine, peaking at tick 168 = 14:00, shifted per district."""
    amp_mult, shift, base_mult = C.TRAFFIC_PROFILE.get(agg_id, (1.0, 0, 1.0))
    tod = tick % C.TICKS_PER_DAY
    phase = 2.0 * math.pi * (tod - C.TRAFFIC_PEAK_TICK - shift) / C.TICKS_PER_DAY
    base = (C.TRAFFIC_BASE * base_mult
            + C.TRAFFIC_AMPLITUDE * amp_mult * (math.cos(phase) * 0.5 + 0.5))
    return clamp(base + rng.gauss(0.0, 0.05), 0.05, 1.0)


def ambient_temp(tick: int, weather_temp_delta: float) -> float:
    """Daily sine on a seasonal baseline. Jan ~8 C, Jul ~34 C."""
    day = (C.START_DAY_OF_YEAR + tick // C.TICKS_PER_DAY) % 365
    seasonal = C.AMBIENT_SEASONAL_AMP * math.cos(
        2.0 * math.pi * (day - 200) / 365.0)
    tod = tick % C.TICKS_PER_DAY
    daily = C.AMBIENT_DAILY_AMP * math.cos(
        2.0 * math.pi * (tod - C.AMBIENT_PEAK_TICK) / C.TICKS_PER_DAY)
    return C.AMBIENT_BASE_C + seasonal + daily + weather_temp_delta


def update_thermal(node, tick: int, weather_temp_delta: float, rng) -> None:
    if node.status == C.STATUS_OVERHEAT:
        return                                     # the fault owns temperature
    amb = ambient_temp(tick, weather_temp_delta)
    # clogged filters reduce cooling capacity — the slow dust signature
    dust_penalty = node.dust_accum * C.DUST_COOLING_PENALTY
    tgt = (amb + node.cpu_load * C.TEMP_PER_CPU_PCT + dust_penalty
           + C.GEN_TEMP_OFFSET[node.generation])
    node.temperature += (tgt - node.temperature) * C.TEMP_CONVERGENCE
    node.temperature += rng.gauss(0.0, C.TEMP_NOISE_SIGMA)
    node.temperature = clamp(node.temperature, 5.0, 95.0)


def update_cpu(node, rng) -> None:
    if node.status == C.STATUS_CONGESTION:
        return                                     # the fault owns CPU
    tgt = 20.0 + node.traffic_load * 55.0
    node.cpu_load += (tgt - node.cpu_load) * 0.30 + rng.gauss(0.0, 1.5)
    node.cpu_load = clamp(node.cpu_load, 5.0, 99.0)


def update_dust(node, weather_type: str, rain_mm_h: float) -> None:
    if weather_type == "Dust":
        node.dust_accum = min(1.0, node.dust_accum + C.DUST_ACCUM_PER_TICK)
    elif rain_mm_h >= C.RAIN_WASH_THRESHOLD:
        node.dust_accum = max(0.0, node.dust_accum - 0.05)


def update_power(node, tick: int, rng) -> None:
    """Grid -> Solar -> Battery -> Generator, with capacity fade."""
    tod = tick % C.TICKS_PER_DAY
    solar_window = C.SOLAR_START_TICK <= tod <= C.SOLAR_END_TICK
    tier = node.grid_tier

    if node.grid_available:
        if rng.random() < C.GRID_DROPOUT_CHANCE[tier]:
            node.grid_available = False
            node.battery_cycles += 0.4          # a shallow cycle begins
    else:
        if rng.random() < C.GRID_RESTORE_CHANCE[tier]:
            node.grid_available = True

    # capacity fades with accumulated cycling. Bakrajo's mains instability
    # means frequent cycling, so its backup window shrinks measurably over a
    # year: 6.0 h -> 4.96 h. Salim Street barely moves.
    node.battery_capacity = max(
        C.BATTERY_CAPACITY_FLOOR,
        100.0 - node.battery_cycles * C.BATTERY_FADE_PER_CYCLE)

    drain = 100.0 / (C.BATTERY_TICKS * node.battery_capacity / 100.0)

    if node.grid_available:
        node.power_source = "Grid"
        node.battery_pct = min(node.battery_capacity,
                               node.battery_pct + C.GRID_CHARGE_PCT)
        node.generator_fuel_pct = min(100.0, node.generator_fuel_pct + 0.3)
        node.voltage = C.VOLTAGE_GRID + rng.gauss(0.0, C.VOLTAGE_NOISE)
        return

    if solar_window and node.battery_pct < node.battery_capacity:
        node.power_source = "Solar"
        soiling = 1.0 - node.dust_accum * C.DUST_SOLAR_PENALTY
        charge = C.SOLAR_CHARGE_PCT * soiling * (1.0 + rng.uniform(-0.2, 0.2))
        node.battery_pct = min(node.battery_capacity,
                               node.battery_pct + charge - drain)
    elif node.battery_pct > C.GEN_START_BATTERY_PCT:
        node.power_source = "Battery"
        node.battery_pct = max(0.0, node.battery_pct - drain)
    elif node.generator_fuel_pct > 0.0:
        node.power_source = "Generator"
        node.generator_fuel_pct = max(
            0.0, node.generator_fuel_pct - (100.0 / C.GENERATOR_TICKS))
        node.battery_pct = min(node.battery_capacity, node.battery_pct + 1.0)
    else:
        node.power_source = "Battery"
        node.battery_pct = max(0.0, node.battery_pct - drain)

    frac = node.battery_pct / 100.0
    node.voltage = (C.VOLTAGE_BATT_EMPTY
                    + (C.VOLTAGE_BATT_FULL - C.VOLTAGE_BATT_EMPTY) * frac
                    + rng.gauss(0.0, C.VOLTAGE_NOISE))


def rain_fade_db(rain_mm_h: float) -> float:
    """ITU-R P.530 rain attenuation on the 23 GHz core link.

    Makes the dual-core design physically real: storms threaten the microwave
    path while fiber is unaffected, and construction threatens fiber while
    microwave is fine.
    """
    if rain_mm_h <= 0.0:
        return 0.0
    gamma = C.MW_ITU_K * (rain_mm_h ** C.MW_ITU_ALPHA)
    d_eff = C.MW_PATH_KM / (1.0 + C.MW_PATH_KM / (35.0 * math.exp(-0.015 * rain_mm_h)))
    return gamma * d_eff
