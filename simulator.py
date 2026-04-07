import sys
import yaml
import numpy as np
import pandas as pd


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def compute_metrics(df, config):
    rpm = df["rpm"].values
    load = df["load"].values
    injection = df["injection_ms"].values
    advance = df["advance_btdc"].values

    rpm_norm = (rpm - config["map"]["rpm_min"]) / (config["map"]["rpm_max"] - config["map"]["rpm_min"])
    load_norm = (load - config["map"]["load_min"]) / (config["map"]["load_max"] - config["map"]["load_min"])

    injection_optimal = 3 + 12 * load_norm * (0.8 + 0.2 * rpm_norm)
    advance_optimal = 35 - 15 * rpm_norm * load_norm

    torque_base = 50 + 200 * load_norm * (1 - 0.3 * (rpm_norm - 0.5) ** 2)
    injection_effect = -2 * (injection - injection_optimal) ** 2
    advance_effect = -1.5 * (advance - advance_optimal) ** 2
    torque = torque_base + injection_effect + advance_effect

    bsfc_base = 250 + 150 * (1 - load_norm) ** 2
    bsfc_injection_penalty = 5 * (injection - injection_optimal * 1.1) ** 2
    bsfc = bsfc_base + bsfc_injection_penalty

    knock_threshold = 30 - 20 * load_norm * rpm_norm
    knock = np.maximum(0, 100 * ((advance - knock_threshold) / 15) ** 2) * (1 + load_norm)

    torque_avg = np.mean(torque)
    bsfc_avg = np.mean(bsfc)
    knock_max = np.max(knock)

    alpha = config["loss_weights"]["alpha"]
    beta = config["loss_weights"]["beta"]
    loss = bsfc_avg - (alpha * torque_avg) + (beta * knock_max)

    return loss, bsfc_avg, torque_avg, knock_max


def validate_map(df, config):
    expected = config["map"]["expected_rows"]
    if len(df) != expected:
        print(f"ERROR: expected {expected} rows, got {len(df)}", file=sys.stderr)
        sys.exit(1)

    inj_min = config["map"]["injection_min"]
    inj_max = config["map"]["injection_max"]
    adv_min = config["map"]["advance_min"]
    adv_max = config["map"]["advance_max"]

    if (df["injection_ms"] < inj_min).any() or (df["injection_ms"] > inj_max).any():
        return False
    if (df["advance_btdc"] < adv_min).any() or (df["advance_btdc"] > adv_max).any():
        return False
    return True


def main():
    if len(sys.argv) != 2:
        print("Usage: python simulator.py map.csv", file=sys.stderr)
        sys.exit(1)

    config = load_config()
    df = pd.read_csv(sys.argv[1])

    if not validate_map(df, config):
        print("loss: 9999.00")
        print("bsfc: 9999.00")
        print("torque_avg: 0.00")
        print("knock_max: 9999.00")
        sys.exit(0)

    loss, bsfc, torque_avg, knock_max = compute_metrics(df, config)
    print(f"loss: {loss:.2f}")
    print(f"bsfc: {bsfc:.2f}")
    print(f"torque_avg: {torque_avg:.2f}")
    print(f"knock_max: {knock_max:.2f}")


if __name__ == "__main__":
    main()
