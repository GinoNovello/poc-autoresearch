import os
import re
import json
import yaml
import subprocess
import time


class LLMClient:
    def __init__(self, config_path="config.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        llm_cfg = self.config["llm"]
        self.model = llm_cfg.get("opencode_model", "zai-coding-plan/glm-5-turbo")
        self.max_retries = llm_cfg.get("max_retries", 3)
        self.retry_backoff_base = llm_cfg.get("retry_backoff_base", 2)
        self.workdir = os.path.dirname(os.path.abspath(config_path))

    def rewrite_tuner(self, program_md, current_tuner, results_history, last_run_log, best_loss, simulator_source):
        prompt = self._build_prompt(
            program_md, current_tuner, results_history, last_run_log, best_loss, simulator_source
        )

        for attempt in range(self.max_retries):
            try:
                print(f"  opencode run (attempt {attempt+1}/{self.max_retries})...")
                result = subprocess.run(
                    [
                        "opencode", "run", prompt,
                        "--model", self.model,
                        "--agent", "build",
                        "--dir", self.workdir,
                    ],
                    capture_output=True, text=True, timeout=300,
                )

                if result.returncode != 0:
                    err = result.stderr[:300]
                    print(f"  opencode error: {err}")
                    if attempt < self.max_retries - 1:
                        backoff = self.retry_backoff_base ** (attempt + 1)
                        print(f"  Retrying in {backoff}s...")
                        time.sleep(backoff)
                        continue
                    return None, f"opencode error: {err}"

                new_tuner = self._read_tuner()
                if new_tuner is None:
                    if attempt < self.max_retries - 1:
                        print(f"  tuner.py not found after run, retrying...")
                        time.sleep(1)
                        continue
                    return None, "tuner.py not found"

                description = self._extract_description(new_tuner)

                if not self._validate_code(new_tuner):
                    if attempt < self.max_retries - 1:
                        print(f"  Invalid code (attempt {attempt+1}), retrying...")
                        time.sleep(2)
                        continue
                    return None, "invalid code"

                return new_tuner, description

            except subprocess.TimeoutExpired:
                if attempt < self.max_retries - 1:
                    backoff = self.retry_backoff_base ** (attempt + 1)
                    print(f"  opencode timeout (attempt {attempt+1}). Retrying in {backoff}s...")
                    time.sleep(backoff)
                else:
                    return None, "opencode timeout after retries"

            except Exception as e:
                if attempt < self.max_retries - 1:
                    backoff = self.retry_backoff_base ** (attempt + 1)
                    print(f"  Error (attempt {attempt+1}): {e}. Retrying in {backoff}s...")
                    time.sleep(backoff)
                else:
                    return None, f"error: {e}"

    def _build_prompt(self, program_md, current_tuner, results_history, last_run_log, best_loss, simulator_source):
        return (
            "CRITICAL RULES:\n"
            "1. You MUST use your Write tool to replace tuner.py on disk. Do NOT just output code.\n"
            "2. You MUST NOT modify any file other than tuner.py.\n"
            "3. You MUST NOT run python, python3, or execute any scripts.\n"
            "4. You MUST NOT read any files — all context is provided below.\n"
            "5. Write the file immediately. Do not analyze or explain.\n\n"
            "You are an automotive engineer expert in ECU calibration. "
            "Rewrite tuner.py to MINIMIZE Loss = BSFC_avg - (alpha * Torque_avg) + (beta * Knock_max). "
            f"alpha={self.config['loss_weights']['alpha']}, beta={self.config['loss_weights']['beta']}.\n\n"
            f"=== INSTRUCTIONS ===\n{program_md}\n\n"
            f"=== CURRENT tuner.py ===\n{current_tuner}\n\n"
            f"=== SIMULATOR FORMULAS (DO NOT MODIFY simulator.py) ===\n"
            "- rpm_norm = (rpm - 800) / 6200, load_norm = (load - 0.1) / 0.9\n"
            "- injection_optimal = 3 + 12 * load_norm * (0.8 + 0.2 * rpm_norm)\n"
            "- advance_optimal = 35 - 15 * rpm_norm * load_norm\n"
            "- torque = 50 + 200*load_norm*(1-0.3*(rpm_norm-0.5)^2) - 2*(inj-inj_opt)^2 - 1.5*(adv-adv_opt)^2\n"
            "- bsfc = 250 + 150*(1-load_norm)^2 + 5*(inj - inj_opt*1.1)^2\n"
            "- knock_threshold = 30 - 20*load_norm*rpm_norm\n"
            "- knock = max(0, 100*((adv-knock_thresh)/15)^2) * (1+load_norm)\n"
            f"- Loss = mean(bsfc) - {self.config['loss_weights']['alpha']}*mean(torque) + {self.config['loss_weights']['beta']}*max(knock)\n"
            "- Ranges: injection 1-20ms, advance 0-45°BTDC, 192 rows (16 RPM x 12 Load)\n"
            "- rpm: np.linspace(800,7000,16), load: np.linspace(0.10,1.00,12)\n"
            "- Out of range → Loss=9999. Optimal Loss < 600 possible.\n\n"
            f"=== EXPERIMENT HISTORY ===\n{results_history}\n\n"
            f"=== LAST RUN LOG ===\n{last_run_log}\n\n"
            f"=== BEST LOSS SO FAR: {best_loss} ===\n\n"
            "Write tuner.py with a new optimization strategy.\n"
            "First line: comment with strategy description (max 80 chars). Example: # Differential Evolution with RPM-dependent bounds\n"
            "MUST define generate_map() that creates map.csv with 192 rows.\n"
            "Allowed: numpy, pandas, scipy, math, random, stdlib.\n"
            "Forbidden: torch, tensorflow, jax, scikit-learn.\n"
            "Use your Write tool NOW to save tuner.py."
        )

    def _summarize_simulator(self, source):
        formulas = []
        formulas.append("RPM: 800-7000 (16 pts), Load: 0.10-1.00 (12 pts). 192 rows total.")
        formulas.append("rpm_norm = (rpm - 800) / 6200, load_norm = (load - 0.1) / 0.9")
        formulas.append("injection_optimal = 3 + 12 * load_norm * (0.8 + 0.2 * rpm_norm)")
        formulas.append("advance_optimal = 35 - 15 * rpm_norm * load_norm")
        formulas.append("torque = 50 + 200*load_norm*(1 - 0.3*(rpm_norm-0.5)^2) - 2*(inj-inj_opt)^2 - 1.5*(adv-adv_opt)^2")
        formulas.append("bsfc = 250 + 150*(1-load_norm)^2 + 5*(inj - inj_opt*1.1)^2")
        formulas.append("knock_threshold = 30 - 20*load_norm*rpm_norm")
        formulas.append("knock = max(0, 100*((adv - knock_thresh)/15)^2) * (1 + load_norm)")
        formulas.append("Loss = mean(bsfc) - 1.0*mean(torque) + 10.0*max(knock)")
        formulas.append("Ranges: injection 1-20ms, advance 0-45deg. Out of range -> Loss=9999.")
        return "\n".join(formulas)

    def _read_tuner(self):
        tuner_path = os.path.join(self.workdir, "tuner.py")
        if not os.path.exists(tuner_path):
            return None
        with open(tuner_path) as f:
            return f.read()

    def _extract_description(self, code):
        for line in code.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("# ").strip()[:80]
        return "iteración"

    def _validate_code(self, code):
        try:
            compile(code, "<tuner>", "exec")
        except SyntaxError:
            return False
        if "def generate_map" not in code:
            return False
        return True
