"""
h2vsiting.py

Shared helpers of the four H2VSiting notebooks: reading config.toml, the run prompts, run names, the matrix info file and the
scaling of the criteria. The notebooks import it from the repository root.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from pyproj import CRS

REPO_DIR = Path(__file__).resolve().parent
CONFIG_PATH = REPO_DIR / "config.toml"

LAYER_KINDS = ("raster", "distance", "presence", "gravity")
VECTOR_EXTS = (".shp", ".gpkg", ".geojson")
RUN_DEFAULTS = {"interactive": True, "resolution": 500, "gravity_alpha": 1.0, "scenario": "Reference",
                "weights": "EWM", "reuse_aligned": False, "compare_classifications": "baseline"}
MATRIX_PATTERN = re.compile(r"^MCDM_Matrix_(.+)_([\d.]+|NA)_([\d.]+m)\.csv$")
RUN_OVERRIDE_ENV = "H2VSITING_RUN"  # JSON with [run] values set by run_workflow.py for the notebook it executes


# --- CONFIGURATION ---
def load_config(path: Path = CONFIG_PATH):
    """Read config.toml, check that it is consistent and return (config, paths).
    cfg["baseline"] keeps the [run] values of the file; cfg["run"] can be overridden by run_workflow.py."""
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    cfg["run"] = RUN_DEFAULTS | cfg.get("run", {})
    cfg["baseline"] = dict(cfg["run"])
    if override := os.environ.get(RUN_OVERRIDE_ENV):
        cfg["run"] |= json.loads(override)
    cfg.setdefault("constraints", [])
    cfg.setdefault("criteria", [])
    cfg.setdefault("validation", {}).setdefault("projects", "")

    errors = []
    layers, scenarios = cfg.get("layers", {}), cfg.get("scenarios", {})
    for name, layer in layers.items():
        if layer.get("kind") not in LAYER_KINDS:
            errors.append(f"[layers.{name}] kind must be one of {', '.join(LAYER_KINDS)}")
        if not layer.get("source"):
            errors.append(f"[layers.{name}] needs a source")
    if not scenarios:
        errors.append("at least one [scenarios.<name>] table is needed")
    for name in scenarios:
        if not re.fullmatch(r"[A-Za-z0-9-]+", name):
            errors.append(f"[scenarios.{name}] names may only use letters, digits and hyphens (they go into file names)")
    for i, rule in enumerate(cfg["constraints"], start=1):
        where = f"constraint {i} ({rule.get('layer')})"
        if rule.get("layer") not in layers:
            errors.append(f"{where}: layer is not defined in [layers]")
        if not any(key in rule for key in ("min", "max", "exclude")):
            errors.append(f"{where}: needs min, max or exclude")
        for key in ("min", "max"):
            if isinstance(rule.get(key), str):
                lacking = [s for s, params in scenarios.items() if rule[key] not in params]
                if lacking:
                    errors.append(f"{where}: {key} = '{rule[key]}' is not a parameter of scenario(s) {', '.join(lacking)}")
    for i, crit in enumerate(cfg["criteria"], start=1):
        where = f"criterion {i} ({crit.get('layer')})"
        if crit.get("layer") not in layers:
            errors.append(f"{where}: layer is not defined in [layers]")
        if crit.get("type") not in ("cost", "benefit"):
            errors.append(f"{where}: type must be cost or benefit")
        if crit.get("transform", "none") not in ("none", "log"):
            errors.append(f"{where}: transform must be none or log")
    run = cfg["run"]
    if run["scenario"] not in scenarios:
        errors.append(f"[run] scenario '{run['scenario']}' is not defined in [scenarios]")
    if run["weights"] not in ("EWM", "CRITIC"):
        errors.append("[run] weights must be EWM or CRITIC")
    if run["compare_classifications"] not in ("baseline", "always", "never"):
        errors.append("[run] compare_classifications must be baseline, always or never")
    if errors:
        raise ValueError(f"{path.name}:\n  " + "\n  ".join(errors))

    data = REPO_DIR / cfg.get("data_dir", "Data")
    raw = data / "Raw Database"
    paths = SimpleNamespace(
        data=data, raw=raw, study_area=raw / cfg["study_area"]["folder"], aligned=data / "Aligned",
        masks=data / "Exclusion Mask", matrices=data / "Matrices", weights=data / "Weights",
        lr=data / "Logistic Regression", scores=data / "Suitability Scores", maps=data / "Suitability Maps",
        figures=data / "Figures",
        projects=raw / cfg["validation"]["projects"] if cfg["validation"]["projects"] else None,
    )
    return cfg, paths


def study_area_file(paths) -> Path:
    """The single polygon file in the study-area folder."""
    found = [p for p in paths.study_area.glob("*") if p.suffix.lower() in VECTOR_EXTS]
    if len(found) != 1:
        raise FileNotFoundError(f"Expected one polygon file ({', '.join(VECTOR_EXTS)}) in {paths.study_area}, "
                                f"found {len(found)}.")
    return found[0]


def crs_label(crs) -> str:
    """'EPSG:<code>' or the CRS name, for figure axes."""
    crs = CRS.from_user_input(crs)
    return f"EPSG:{epsg}" if (epsg := crs.to_epsg()) else crs.name


# --- PROMPTS (press Enter to keep the default; no prompt when interactive = false) ---
def ask_number(question, default, interactive, allowed=None) -> float:
    """A positive number, one of `allowed` if given."""
    while True:
        answer = input(f"{question} [{default:g}]: ").strip().lower().rstrip("m").strip() if interactive else ""
        try:
            value = float(answer.replace(",", ".")) if answer else float(default)
        except ValueError:
            value = None
        if value is not None and value > 0 and (allowed is None or value in allowed):
            return value
        hint = f"one of: {', '.join(f'{a:g}' for a in allowed)}" if allowed else "a positive number"
        if not interactive:
            raise ValueError(f"{question} {default:g} is not valid: use {hint} (config.toml, [run]).")
        print(f"  Please enter {hint}.")


def ask_choice(question, options, default, interactive) -> str:
    """One of `options`, by number or by name."""
    listing = ", ".join(f"{i}={name}" for i, name in enumerate(options, start=1))
    while True:
        answer = input(f"{question} ({listing}) [{default}]: ").strip() if interactive else ""
        if not answer and default in options:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        for name in options:
            if answer.lower() == name.lower():
                return name
        if not interactive:
            raise ValueError(f"{question} '{default}' is not one of: {', '.join(options)} (config.toml, [run]).")
        print(f"  Please choose one of: {listing}")


# --- RUN NAMES: <scenario>_<alpha>_<resolution>, alpha "NA" for a run without gravity criteria ---
def alpha_tag(alpha) -> str:
    return "NA" if alpha is None else f"{alpha:g}"


def find_runs(cfg, paths):
    """The MCDM matrices built by 02, sorted by resolution, alpha and scenario order in config.toml."""
    order = list(cfg["scenarios"])
    runs = []
    for f in paths.matrices.glob("MCDM_Matrix_*.csv"):
        if m := MATRIX_PATTERN.match(f.name):
            scenario, alpha, res = m.groups()
            runs.append(SimpleNamespace(matrix=f, scenario=scenario, alpha=alpha, res=res,
                                        tag=f"{scenario}_{alpha}_{res}"))
    runs.sort(key=lambda r: (float(r.res[:-1]), -1.0 if r.alpha == "NA" else float(r.alpha),
                             order.index(r.scenario) if r.scenario in order else len(order), r.scenario))
    return runs


def _matches(params, run) -> bool:
    return (run.scenario == params["scenario"] and float(run.res[:-1]) == params["resolution"]
            and (run.alpha == "NA" or float(run.alpha) == params["gravity_alpha"]))


def is_baseline(cfg, run) -> bool:
    """True for the run that matches scenario, gravity_alpha and resolution in [run] of config.toml."""
    return _matches(cfg["baseline"], run)


def choose_run(cfg, runs, usable=lambda run: True, unusable_note=""):
    """List the runs and return the one chosen. The default is the run of the current [run] values;
    without prompts (interactive = false) it must exist."""
    interactive = cfg["run"]["interactive"]
    wanted = next((run for run in runs if _matches(cfg["run"], run)), None)
    if not interactive:
        c = cfg["run"]
        if wanted is None:
            raise FileNotFoundError(f"No MCDM matrix for scenario {c['scenario']}, alpha {c['gravity_alpha']:g}, "
                                    f"{c['resolution']:g} m. Run 02_Matrix_Preparation with these values first.")
        if not usable(wanted):
            raise FileNotFoundError(f"{wanted.matrix.name}: {unusable_note}.")
        print(f"Matrix: {wanted.matrix.name}")
        return wanted
    ok = [i for i, run in enumerate(runs, start=1) if usable(run)]
    if not ok:
        raise FileNotFoundError("No usable MCDM matrix found. Run the previous notebooks first.")
    for i, run in enumerate(runs, start=1):
        print(f"  {i}. {run.scenario:<13} alpha {run.alpha:<5} {run.res}" + ("" if usable(run) else f"  ({unusable_note})"))
    default = next((i for i in ok if runs[i - 1] is wanted),
                   next((i for i in ok if runs[i - 1].scenario == cfg["run"]["scenario"]), ok[0]))
    while True:
        answer = input(f"Which matrix? (1-{len(runs)}) [{default}]: ").strip() if interactive else ""
        if not answer:
            return runs[default - 1]
        if answer.isdigit() and int(answer) in ok:
            return runs[int(answer) - 1]
        print("  Please choose a listed matrix" + (f" without '{unusable_note}'." if unusable_note else "."))


# --- MATRIX INFO: the criteria of a matrix, written by 02 next to the CSV ---
def write_matrix_info(matrix_path: Path, criteria) -> None:
    with open(matrix_path.with_suffix(".json"), "w", encoding="utf-8") as f:
        json.dump(criteria, f, indent=2, ensure_ascii=False)


def read_matrix_info(matrix_path: Path):
    path = matrix_path.with_suffix(".json")
    if not path.exists():
        raise FileNotFoundError(f"{path.name} not found. Re-run 02_Matrix_Preparation for this matrix.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --- SCALING OF THE CRITERIA ---
def transformed(values, crit):
    """Values after the criterion's transform (log for heavy-tailed layers such as gravity)."""
    values = np.asarray(values, dtype=float)
    return np.log(values) if crit["transform"] == "log" else values


def normalized(values, crit):
    """0-1 scale for the weights and the figures: transform, then min-max (costs inverted).
    A criterion with scaled = true is already on a 0-1 benefit scale and is left unchanged."""
    values = transformed(values, crit)
    if crit["scaled"]:
        return values
    lo, hi = values.min(), values.max()
    if hi == lo:
        return np.zeros_like(values)
    return (hi - values) / (hi - lo) if crit["type"] == "cost" else (values - lo) / (hi - lo)
