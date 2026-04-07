# 1D knock-budget optimizer: balance torque gain vs knock penalty
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar


def generate_map():
    rpms = np.linspace(800, 7000, 16)
    loads = np.linspace(0.10, 1.00, 12)
    RN, LN = np.meshgrid((rpms - 800) / 6200, (loads - 0.1) / 0.9, indexing="ij")

    inj_opt = 3.0 + 12.0 * LN * (0.8 + 0.2 * RN)
    injection = (15.0 / 14.0) * inj_opt

    adv_opt = 35.0 - 15.0 * RN * LN
    knock_thr = 30.0 - 20.0 * RN * LN
    gap = adv_opt - knock_thr
    knock_at_opt = (100.0 / 225.0) * gap ** 2 * (1.0 + LN)

    torque_base = (
        50.0 + 200.0 * LN * (1.0 - 0.3 * (RN - 0.5) ** 2)
        - 2.0 * (injection - inj_opt) ** 2
    )
    bsfc = 250.0 + 150.0 * (1.0 - LN) ** 2 + 5.0 * (injection - inj_opt * 1.1) ** 2

    def total_loss(K):
        delta = np.where(
            knock_at_opt <= K,
            gap,
            15.0 * np.sqrt(K / (100.0 * (1.0 + LN))),
        )
        adv = np.clip(knock_thr + delta, 0.0, 45.0)
        torque = torque_base - 1.5 * (adv - adv_opt) ** 2
        knock = np.maximum(0, 100.0 * ((adv - knock_thr) / 15.0) ** 2) * (1.0 + LN)
        return np.mean(bsfc) - np.mean(torque) + 10.0 * np.max(knock)

    res = minimize_scalar(total_loss, bounds=(0, 10), method="bounded")
    K = res.x

    delta = np.where(
        knock_at_opt <= K,
        gap,
        15.0 * np.sqrt(K / (100.0 * (1.0 + LN))),
    )
    advance = np.clip(knock_thr + delta, 0.0, 45.0)

    RPM, LOAD = np.meshgrid(rpms, loads, indexing="ij")
    rows = []
    for i in range(16):
        for j in range(12):
            rows.append({
                "rpm": round(float(RPM[i, j]), 2),
                "load": round(float(LOAD[i, j]), 2),
                "injection_ms": round(float(injection[i, j]), 6),
                "advance_btdc": round(float(advance[i, j]), 6),
            })

    pd.DataFrame(rows).to_csv("map.csv", index=False)


if __name__ == "__main__":
    generate_map()
