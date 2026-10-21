"""
run_workflow.py

Runs the whole workflow (notebooks 01 -> 04) in one go. It asks for every parameter first, then executes the notebooks
on its own, without further prompts. Several resolutions, alphas, scenarios and weighting methods can be given at once,
comma-separated: every combination is run. The executed notebooks, with all their outputs, are saved in Data/Executed/.

Run from the repository root:
    python run_workflow.py             # asks for the parameters (Enter keeps the default from config.toml)
    python run_workflow.py --defaults  # no questions: the [run] values of config.toml
"""

from __future__ import annotations

import argparse
import json
import os
import time

import nbformat
from ipykernel.kernelspec import get_kernel_dict
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpec, KernelSpecManager
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

from h2vsiting import REPO_DIR, RUN_OVERRIDE_ENV, alpha_tag, load_config

NOTEBOOKS = {1: "01_Data_Preprocessing", 2: "02_Matrix_Preparation", 3: "03_Criteria_Weighting",
             4: "04_Criteria_Aggregation"}
WEIGHT_METHODS = ("EWM", "CRITIC")


class ThisPython(KernelSpecManager):
    """Runs the notebooks with the Python that runs this script (its environment), whatever kernels are installed."""

    def get_kernel_spec(self, kernel_name):
        return KernelSpec(resource_dir="", **get_kernel_dict())


# --- QUESTIONS ---
def ask_values(question, default, convert, hint, every=None):
    """Comma-separated values (Enter keeps the default; "all" gives `every` if it is set)."""
    while True:
        answer = input(f"{question} [{default}]: ").strip() or str(default)
        if every is not None and answer.lower() == "all":
            return list(every)
        try:
            values = [convert(item.strip()) for item in answer.split(",") if item.strip()]
        except (ValueError, KeyError):
            values = []
        if values:
            return list(dict.fromkeys(values))  # without repeats, in the order given
        print(f"  Please enter {hint}.")


def positive(text):
    value = float(text.lower().rstrip("m"))
    if value <= 0:
        raise ValueError
    return value


def by_name(options):
    """Converter that accepts a name (any case) or its number in `options`."""
    def convert(text):
        if text.isdigit() and 1 <= int(text) <= len(options):
            return options[int(text) - 1]
        return {name.lower(): name for name in options}[text.lower()]
    return convert


def ask_steps(default="1-4"):
    while True:
        answer = (input(f"Notebooks to run (e.g. 1-4, 2-4, 4) [{default}]: ").strip() or default).replace(" ", "")
        try:
            first, _, last = answer.partition("-")
            steps = list(range(int(first), int(last or first) + 1))
        except ValueError:
            steps = []
        if steps and all(step in NOTEBOOKS for step in steps):
            return steps
        print("  Please enter a notebook number or a range between 1 and 4.")


def ask_yes_no(question, default):
    while True:
        answer = input(f"{question} [{'y' if default else 'n'}]: ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes", "n", "no"):
            return answer.startswith("y")
        print("  Please answer y or n.")


def parameters(cfg, use_defaults):
    """Every parameter of the runs, asked in advance (or the [run] values of config.toml)."""
    run, scenarios = cfg["run"], list(cfg["scenarios"])
    has_gravity = any(cfg["layers"][c["layer"]]["kind"] == "gravity" for c in cfg["criteria"])
    if use_defaults:
        return dict(steps=list(NOTEBOOKS), resolutions=[run["resolution"]],
                    alphas=[run["gravity_alpha"]] if has_gravity else [None], scenarios=[run["scenario"]],
                    weights=[run["weights"]], reuse_aligned=run["reuse_aligned"])
    print("Parameters (press Enter to keep the default from config.toml; several values: comma-separated)\n")
    steps = ask_steps()
    p = dict(steps=steps, resolutions=ask_values("Grid resolution (m)", f"{run['resolution']:g}", positive,
                                                 "positive numbers, e.g. 500 or 500, 1000"))
    p["alphas"] = (ask_values("Gravity alpha", f"{run['gravity_alpha']:g}", positive, "positive numbers, e.g. 1 or 0.5, 1, 2")
                   if has_gravity else [None])
    p["scenarios"] = ([] if steps == [1] else
                      ask_values(f"Scenario ({', '.join(f'{i}={s}' for i, s in enumerate(scenarios, 1))}, or all)",
                                 run["scenario"], by_name(scenarios), "scenario names or numbers", every=scenarios))
    p["weights"] = (ask_values("Weighting method (EWM, CRITIC, or all)", run["weights"], by_name(WEIGHT_METHODS),
                               "EWM and/or CRITIC", every=WEIGHT_METHODS) if 4 in steps else [])
    p["reuse_aligned"] = (ask_yes_no("Keep aligned layers that already exist (reuse_aligned)?", run["reuse_aligned"])
                          if 1 in steps else run["reuse_aligned"])
    return p


# --- EXECUTION ---
def execute(name, params, tag, out_dir):
    """Execute one notebook with the given [run] values and save it, with its outputs, in out_dir."""
    nb = nbformat.read(REPO_DIR / f"{name}.ipynb", as_version=4)
    os.environ[RUN_OVERRIDE_ENV] = json.dumps(params | {"interactive": False})  # read by load_config in the kernel
    km = KernelManager(kernel_spec_manager=ThisPython(), kernel_name="python3")
    client = NotebookClient(nb, km=km, timeout=None, resources={"metadata": {"path": str(REPO_DIR)}})
    out_path = out_dir / f"{name}_{tag}.ipynb"
    print(f"  {name} ({tag}) ...", end=" ", flush=True)
    start = time.time()
    try:
        client.execute()
    except CellExecutionError as error:
        nbformat.write(nb, out_path)
        print("FAILED\n")
        print("\n".join(str(error).strip().splitlines()[-3:]))
        raise SystemExit(f"\nStopped. The notebook with the error is saved in {out_path}")
    finally:
        if km.has_kernel:
            km.shutdown_kernel(now=True)  # frees the notebook's memory before the next one starts
    nbformat.write(nb, out_path)
    print(f"done ({time.time() - start:.0f} s)")


def main():
    parser = argparse.ArgumentParser(description="Run notebooks 01-04 in one go.")
    parser.add_argument("--defaults", action="store_true", help="no questions: use the [run] values of config.toml")
    args = parser.parse_args()

    cfg, paths = load_config()
    p = parameters(cfg, args.defaults)
    out_dir = paths.data / "Executed"
    out_dir.mkdir(parents=True, exist_ok=True)

    n_runs = len(p["resolutions"]) * len(p["alphas"]) * max(len(p["scenarios"]), 1)
    print(f"\nRunning notebooks {', '.join(f'{s:02d}' for s in p['steps'])} for {n_runs} run(s) "
          f"(resolution x alpha x scenario). Executed notebooks: {out_dir}\n")
    start = time.time()
    for res in p["resolutions"]:
        for i, alpha in enumerate(p["alphas"]):
            base = {"resolution": res, "gravity_alpha": cfg["run"]["gravity_alpha"] if alpha is None else alpha}
            res_tag, a_tag = f"{res:g}m", alpha_tag(alpha)
            if 1 in p["steps"]:
                # After the first alpha, the layers without alpha already exist: only the gravity layers are new
                execute(NOTEBOOKS[1], base | {"reuse_aligned": p["reuse_aligned"] or i > 0}, f"{a_tag}_{res_tag}", out_dir)
            for scenario in p["scenarios"]:
                run_tag = f"{scenario}_{a_tag}_{res_tag}"
                params = base | {"scenario": scenario}
                for step in (2, 3):
                    if step in p["steps"]:
                        execute(NOTEBOOKS[step], params, run_tag, out_dir)
                if 4 in p["steps"]:
                    for method in p["weights"]:
                        execute(NOTEBOOKS[4], params | {"weights": method}, f"{method}_{run_tag}", out_dir)
    print(f"\nAll done in {(time.time() - start) / 60:.1f} min. Results in {paths.data}")


if __name__ == "__main__":
    main()
