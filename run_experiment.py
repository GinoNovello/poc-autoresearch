import os
import sys
import csv
import subprocess
import yaml
from datetime import datetime
from pathlib import Path

from llm_client import LLMClient


RESULTS_HEADER = "iteration\tcommit\tdescription\tloss\tbsfc\ttorque_avg\tknock_max\tstatus\n"
RESULTS_FILE = "results.tsv"
RUN_LOG = "run.log"
MAP_FILE = "map.csv"
TUNER_FILE = "tuner.py"
SIMULATOR_FILE = "simulator.py"
PROGRAM_FILE = "program.md"
CONFIG_FILE = "config.yaml"


def load_config():
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def get_commit_hash():
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip()


def get_commit_count():
    result = subprocess.run(["git", "rev-list", "--count", "HEAD"], capture_output=True, text=True)
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def git_init_branch():
    now = datetime.now().strftime("%Y-%m-%d-%H%M")
    branch_name = f"autotuner/{now}"
    subprocess.run(["git", "checkout", "-b", branch_name], capture_output=True)
    return branch_name


def git_commit_tuner(message):
    subprocess.run(["git", "add", TUNER_FILE], capture_output=True)
    subprocess.run(["git", "commit", "-m", message], capture_output=True)
    return get_commit_hash()


def git_reset_last():
    subprocess.run(["git", "reset", "--hard", "HEAD~1"], capture_output=True)


def init_results():
    if not os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "w") as f:
            f.write(RESULTS_HEADER)


def append_result(iteration, commit, description, loss, bsfc, torque_avg, knock_max, status):
    with open(RESULTS_FILE, "a") as f:
        f.write(f"{iteration}\t{commit}\t{description}\t{loss}\t{bsfc}\t{torque_avg}\t{knock_max}\t{status}\n")


def read_last_n_results(n):
    if not os.path.exists(RESULTS_FILE):
        return ""
    with open(RESULTS_FILE) as f:
        lines = f.readlines()
    if len(lines) <= 1:
        return ""
    data_lines = lines[1:]
    return "".join(data_lines[-n:])


def get_best_loss():
    if not os.path.exists(RESULTS_FILE):
        return float("inf")
    best = float("inf")
    with open(RESULTS_FILE) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row.get("status") in ("keep", "baseline"):
                try:
                    loss = float(row["loss"])
                    if loss < best:
                        best = loss
                except (ValueError, KeyError):
                    pass
    return best


def read_file(path):
    if not os.path.exists(path):
        return ""
    with open(path) as f:
        return f.read()


def run_tuner(timeout):
    try:
        result = subprocess.run(
            [sys.executable, TUNER_FILE],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return False, result.stderr
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT: tuner.py excedió el límite de tiempo"
    except Exception as e:
        return False, str(e)


def run_simulator():
    try:
        result = subprocess.run(
            [sys.executable, SIMULATOR_FILE, MAP_FILE],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"ERROR CRÍTICO: simulator.py falló: {result.stderr}")
            sys.exit(1)
        return result.stdout.strip()
    except Exception as e:
        print(f"ERROR CRÍTICO: simulator.py falló: {e}")
        sys.exit(1)


def parse_simulator_output(output):
    metrics = {}
    for line in output.split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            metrics[key.strip()] = float(val.strip())
    return metrics


def validate_map(config):
    if not os.path.exists(MAP_FILE):
        return False, "map.csv no fue creado"

    with open(MAP_FILE) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    expected = config["map"]["expected_rows"]
    if len(rows) != expected:
        return False, f"esperadas {expected} filas, obtenidas {len(rows)}"

    inj_min = config["map"]["injection_min"]
    inj_max = config["map"]["injection_max"]
    adv_min = config["map"]["advance_min"]
    adv_max = config["map"]["advance_max"]

    for i, row in enumerate(rows):
        try:
            inj = float(row["injection_ms"])
            adv = float(row["advance_btdc"])
            if inj < inj_min or inj > inj_max:
                return False, f"fila {i+1}: inyección {inj} fuera de rango [{inj_min},{inj_max}]"
            if adv < adv_min or adv > adv_max:
                return False, f"fila {i+1}: avance {adv} fuera de rango [{adv_min},{adv_max}]"
        except (ValueError, KeyError) as e:
            return False, f"fila {i+1}: error parseando valores: {e}"

    return True, ""


def cleanup_map():
    if os.path.exists(MAP_FILE):
        os.remove(MAP_FILE)


PROTECTED_FILES = {
    SIMULATOR_FILE, PROGRAM_FILE, CONFIG_FILE, "opencode.json",
    "requirements.txt", ".gitignore", "llm_client.py", "run_experiment.py",
}


def protect_files():
    result = subprocess.run(
        ["git", "diff", "--name-only"], capture_output=True, text=True,
    )
    changed = [f for f in result.stdout.strip().split("\n") if f]
    touched_protected = [f for f in changed if f in PROTECTED_FILES]
    if touched_protected:
        print(f"  ⚠ Revirtiendo archivos protegidos modificados: {touched_protected}")
        for f in touched_protected:
            subprocess.run(["git", "checkout", "--", f], capture_output=True)


def setup(config):
    for f in [SIMULATOR_FILE, TUNER_FILE]:
        if not os.path.exists(f):
            print(f"ERROR: {f} no existe")
            sys.exit(1)

    branch = git_init_branch()
    print(f"Branch creado: {branch}")

    init_results()

    print("Ejecutando baseline...")
    ok, err = run_tuner(config["experiment"]["timeout_seconds"])
    if not ok:
        print(f"ERROR: tuner.py base falló: {err}")
        sys.exit(1)

    sim_output = run_simulator()
    metrics = parse_simulator_output(sim_output)
    loss = metrics["loss"]

    log_entry = (
        f"=== BASELINE ===\n"
        f"loss: {metrics['loss']}\n"
        f"bsfc: {metrics['bsfc']}\n"
        f"torque_avg: {metrics['torque_avg']}\n"
        f"knock_max: {metrics['knock_max']}\n"
    )
    with open(RUN_LOG, "w") as f:
        f.write(log_entry)

    commit = git_commit_tuner("baseline: grid search with fixed values")
    append_result(0, commit, "baseline grid search", metrics["loss"], metrics["bsfc"], metrics["torque_avg"], metrics["knock_max"], "baseline")
    cleanup_map()

    print(f"Baseline Loss: {loss:.2f}")
    return loss


def run_loop(config, llm, best_loss):
    iteration = 0
    timeout = config["experiment"]["timeout_seconds"]
    max_history = config["experiment"]["max_history_in_prompt"]
    max_iters = config["experiment"].get("max_iterations")

    while True:
        iteration += 1
        if max_iters and iteration > max_iters:
            print(f"Máximo de iteraciones alcanzado: {max_iters}")
            break

        print(f"\n{'='*60}")
        print(f"ITERACIÓN #{iteration} | Mejor Loss: {best_loss:.2f}")
        print(f"{'='*60}")

        program_md = read_file(PROGRAM_FILE)
        current_tuner = read_file(TUNER_FILE)
        results_history = read_last_n_results(max_history)
        last_run_log = read_file(RUN_LOG)
        simulator_source = read_file(SIMULATOR_FILE)
        best_loss_ctx = get_best_loss()

        print("  Enviando al LLM (via opencode)...")
        tuner_before = read_file(TUNER_FILE)

        new_code, description = llm.rewrite_tuner(
            program_md, current_tuner, results_history, last_run_log,
            best_loss_ctx, simulator_source,
        )

        protect_files()

        if new_code is None:
            print(f"  ✗ Código inválido o error: {description}")
            with open(TUNER_FILE, "w") as f:
                f.write(tuner_before)
            append_result(iteration, "", description[:80], 0, 0, 0, 0, "invalid")
            continue

        if new_code == tuner_before:
            print(f"  ✗ tuner.py no fue modificado por el LLM")
            append_result(iteration, "", "no change", 0, 0, 0, 0, "invalid")
            continue

        print(f"  Estrategia: {description}")

        commit = git_commit_tuner(f"experiment #{iteration}: {description}")
        print(f"  Commit: {commit}")

        print("  Ejecutando tuner.py...")
        ok, err = run_tuner(timeout)
        if not ok:
            print(f"  ✗ CRASH: {err}")
            with open(RUN_LOG, "w") as f:
                f.write(f"=== EXPERIMENTO #{iteration} ===\nstatus: CRASH\nerror: {err}\n")
            git_reset_last()
            append_result(iteration, commit, description[:80], 0, 0, 0, 0, "crash")
            cleanup_map()
            continue

        valid, err = validate_map(config)
        if not valid:
            print(f"  ✗ MAPA INVÁLIDO: {err}")
            with open(RUN_LOG, "w") as f:
                f.write(f"=== EXPERIMENTO #{iteration} ===\nstatus: CRASH\nerror: {err}\n")
            git_reset_last()
            append_result(iteration, commit, description[:80], 0, 0, 0, 0, "crash")
            cleanup_map()
            continue

        print("  Evaluando con simulador...")
        sim_output = run_simulator()
        metrics = parse_simulator_output(sim_output)
        loss = metrics["loss"]

        log_entry = (
            f"=== EXPERIMENTO #{iteration} ===\n"
            f"estrategia: {description}\n"
            f"{sim_output}\n"
        )
        with open(RUN_LOG, "w") as f:
            f.write(log_entry)

        print(f"  Loss: {loss:.2f} | BSFC: {metrics['bsfc']:.2f} | Torque: {metrics['torque_avg']:.2f} | Knock: {metrics['knock_max']:.2f}")

        if loss < best_loss:
            print(f"  ✓ KEEP — Nuevo mejor Loss: {loss:.2f} (anterior: {best_loss:.2f})")
            best_loss = loss
            append_result(iteration, commit, description[:80], metrics["loss"], metrics["bsfc"], metrics["torque_avg"], metrics["knock_max"], "keep")
        else:
            print(f"  ✗ DISCARD — Loss {loss:.2f} no mejoró {best_loss:.2f}")
            commit_count = get_commit_count()
            if commit_count <= 1:
                print("  WARNING: Solo hay 1 commit (baseline). Restaurando tuner.py manualmente.")
                baseline_tuner = subprocess.run(
                    ["git", "show", "HEAD:tuner.py"], capture_output=True, text=True,
                )
                with open(TUNER_FILE, "w") as f:
                    f.write(baseline_tuner.stdout)
            else:
                git_reset_last()
            append_result(iteration, commit, description[:80], metrics["loss"], metrics["bsfc"], metrics["torque_avg"], metrics["knock_max"], "discard")

        cleanup_map()


def main():
    os.chdir(Path(__file__).parent)
    config = load_config()

    print("AutoTuner-PoC — Agente Autónomo de Calibración de ECU")
    print("=" * 60)

    best_loss = setup(config)
    llm = LLMClient()

    print("\nIniciando loop de experimentación (Ctrl+C para detener)...\n")

    try:
        run_loop(config, llm, best_loss)
    except KeyboardInterrupt:
        print("\n\nExperimentación detenida por el usuario.")
        final_best = get_best_loss()
        print(f"Mejor Loss alcanzado: {final_best:.2f}")


if __name__ == "__main__":
    main()
