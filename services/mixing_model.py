"""A basic model of mixer power draw, trained on the mixing runs in the database.

Question it answers: given how the mixer was set and how far through the run it is,
how much power does it draw? At a fixed speed the power rises with the slurry's
viscosity, so a model that follows the power through a run is following the slurry as
solvent is added.

Every stage is predicted by a model that never saw that stage (leave-one-stage-out),
so a second of power is never predicted from its own neighbours. The result is
compared with simply guessing the average.
"""

import numpy as np
import pandas as pd

MIN_STAGES = 4
MAX_SCATTER_POINTS = 800

FEATURES = (
    "rotor_rpm",
    "t_in_stage_s",
    "pause_before_s",
    "energy_before_kj",
    "stage_no",
)
LABELS = {
    "rotor_rpm": "Rotor speed",
    "t_in_stage_s": "Time in stage",
    "pause_before_s": "Pause before stage",
    "energy_before_kj": "Energy used so far",
    "stage_no": "Stage number",
}


class ModelError(ValueError):
    """There is not enough data to train; the message is shown to the user."""


def build_table(runs):
    """One row per second of rotor-on time. runs: (mixing_id, log, stages) tuples."""
    parts = []
    for mixing_id, log, stages in runs:
        energy_so_far = 0.0
        for s in stages.itertuples():
            part = log[
                (log["t_s"] >= s.start_s) & (log["t_s"] < s.start_s + s.duration_s)
            ].copy()
            part["mixing_id"], part["stage_no"] = mixing_id, s.stage_no
            part["t_in_stage_s"] = part["t_s"] - s.start_s
            part["pause_before_s"] = s.pause_before_s
            part["energy_before_kj"] = energy_so_far
            part["group"] = f"{mixing_id}#{s.stage_no}"
            energy_so_far += s.energy_kj
            parts.append(part)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def make_model():
    from sklearn.ensemble import GradientBoostingRegressor

    return GradientBoostingRegressor(
        n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=0
    )


def train_and_score(runs):
    """Train on every run and score it with leave-one-stage-out.

    Returns a dict for the page: metrics, feature importance, a scatter sample and,
    for each run, measured and held-out predicted power against time.
    """
    from sklearn.dummy import DummyRegressor
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import mean_absolute_error, r2_score
    from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict

    data = build_table(runs)
    stage_count = data["group"].nunique() if len(data) else 0
    if stage_count < MIN_STAGES:
        raise ModelError(
            f"Need at least {MIN_STAGES} mixing stages to train; found {stage_count}."
        )

    X, y, groups = data[list(FEATURES)], data["total_power_w"], data["group"]
    cv = LeaveOneGroupOut()
    predicted = cross_val_predict(make_model(), X, y, groups=groups, cv=cv)
    baseline = cross_val_predict(DummyRegressor(), X, y, groups=groups, cv=cv)
    data["predicted"] = predicted

    final = make_model().fit(X, y)
    importance = permutation_importance(final, X, y, n_repeats=5, random_state=0)
    ranked = sorted(
        zip(FEATURES, importance.importances_mean, strict=True),
        key=lambda item: item[1],
    )

    pick = np.linspace(0, len(data) - 1, min(len(data), MAX_SCATTER_POINTS)).astype(int)
    per_run = {}
    for mixing_id, part in data.groupby("mixing_id"):
        part = part.sort_values("t_s")
        per_run[mixing_id] = {
            "t_s": part["t_s"].astype(int).tolist(),
            "actual": part["total_power_w"].round(1).tolist(),
            "predicted": part["predicted"].round(1).tolist(),
        }

    return {
        "runs": len(per_run),
        "stages": int(stage_count),
        "seconds": int(len(data)),
        "r2": float(r2_score(y, predicted)),
        "mae_w": float(mean_absolute_error(y, predicted)),
        "baseline_r2": float(r2_score(y, baseline)),
        "baseline_mae_w": float(mean_absolute_error(y, baseline)),
        "importance": [
            {"feature": LABELS[name], "value": round(float(value), 4)}
            for name, value in ranked
        ],
        "scatter": {
            "actual": y.iloc[pick].round(1).tolist(),
            "predicted": data["predicted"].iloc[pick].round(1).tolist(),
        },
        "per_run": per_run,
    }
