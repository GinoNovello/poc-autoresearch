# Exact analytical optimum: knock=0 everywhere, optimal injection blend
import numpy as np
import pandas as pd


def generate_map():
    rpms = np.linspace(800, 7000, 16)
    loads = np.linspace(0.10, 1.00, 12)

    rn = (rpms - 800.0) / 6200.0
    ln = (loads - 0.10) / 0.9

    RN, LN = np.meshgrid(rn, ln, indexing="ij")
    RPM, LOAD = np.meshgrid(rpms, loads, indexing="ij")

    inj_opt = 3.0 + 12.0 * LN * (0.8 + 0.2 * RN)
    injection = np.clip((15.0 / 14.0) * inj_opt, 1.0, 20.0)

    advance = 30.0 - 20.0 * RN * LN

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
