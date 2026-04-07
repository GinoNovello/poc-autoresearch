# Analytical injection + water-filling advance (scipy optimized)
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar


def generate_map():
    rpms = np.linspace(800, 7000, 16)
    loads = np.linspace(0.10, 1.00, 12)

    rn = (rpms - 800.0) / 6200.0
    ln = (loads - 0.10) / 0.9

    RN, LN = np.meshgrid(rn, ln, indexing="ij")
    RPM, LOAD = np.meshgrid(rpms, loads, indexing="ij")

    inj_opt = 3.0 + 12.0 * LN * (0.8 + 0.2 * RN)
    injection = np.clip((15.0 / 14.0) * inj_opt, 1.0, 20.0)

    adv_opt = 35.0 - 15.0 * RN * LN
    knock_thresh = 30.0 - 20.0 * RN * LN

    torque_base = 50 + 200 * LN * (1 - 0.3 * (RN - 0.5) ** 2)
    bsfc_base = 250 + 150 * (1 - LN) ** 2
    inj_eff = -2.0 * (injection - inj_opt) ** 2
    bsfc_inj = 5.0 * (injection - inj_opt * 1.1) ** 2

    def loss_for_K(K):
        delta = 15.0 * np.sqrt(K / (100.0 * (1.0 + LN)))
        advance = knock_thresh + delta

        torque = torque_base + inj_eff - 1.5 * (advance - adv_opt) ** 2
        bsfc = bsfc_base + bsfc_inj
        knock = np.maximum(0.0, 100.0 * ((advance - knock_thresh) / 15.0) ** 2) * (1.0 + LN)

        return np.mean(bsfc) - np.mean(torque) + 10.0 * np.max(knock)

    res = minimize_scalar(loss_for_K, bounds=(0.0, 50.0), method="bounded")
    K_opt = res.x

    delta_opt = 15.0 * np.sqrt(K_opt / (100.0 * (1.0 + LN)))
    advance_final = np.clip(knock_thresh + delta_opt, 0.0, 45.0)

    rows = []
    for i in range(16):
        for j in range(12):
            rows.append({
                "rpm": round(float(RPM[i, j]), 2),
                "load": round(float(LOAD[i, j]), 2),
                "injection_ms": round(float(injection[i, j]), 6),
                "advance_btdc": round(float(advance_final[i, j]), 6),
            })

    pd.DataFrame(rows).to_csv("map.csv", index=False)


if __name__ == "__main__":
    generate_map()
