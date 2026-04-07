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
            "You MUST use your file editing tools to rewrite tuner.py on disk. Do NOT just respond with code - actually edit the file.\n"
            "Do NOT modify any file other than tuner.py.\n\n"
            "You are an automotive engineer expert in ECU calibration. "
            "Rewrite tuner.py with a new optimization strategy to MINIMIZE the Loss. "
            "Loss = BSFC_avg - (alpha * Torque_avg) + (beta * Knock_max).\n\n"
            f"=== INSTRUCTIONS (program.md) ===\n{program_md}\n\n"
            f"=== CURRENT tuner.py ===\n{current_tuner}\n\n"
            f"=== SIMULATOR (for reference only, DO NOT MODIFY) ===\n{simulator_source}\n\n"
            f"=== EXPERIMENT HISTORY ===\n{results_history}\n\n"
            f"=== LAST RUN LOG ===\n{last_run_log}\n\n"
            f"=== BEST LOSS SO FAR: {best_loss} ===\n\n"
            "Rewrite tuner.py with a new optimization strategy.\n"
            "Include a comment on the first line with a brief description (max 80 chars).\n"
            "Example: # Differential Evolution with RPM-dependent bounds\n"
            "The file MUST define a function generate_map() that creates map.csv with 192 rows.\n"
            "Allowed libraries: numpy, pandas, scipy, math, random, stdlib.\n"
            "Do NOT use: torch, tensorflow, jax, scikit-learn.\n"
            "Use your Edit or Write tool to save the new tuner.py."
        )

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
