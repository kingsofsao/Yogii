"""Train the Yogii prototype risk model on SYNTHETIC data.

    python ml/train.py [--engine auto|xgboost|numpy] [--rows N]

Pipeline:
  1. Generate synthetic transactions (seed 42) and write data/synthetic_transactions.csv
  2. Time-based split 70 / 15 / 15 (train / validation / test)
  3. Train three XGBoost anomaly models (amount, behavior, context), each on its own label
  4. Fit a linear-regression stacker on the validation slice:
        rating ~ [p_amount, p_behavior, p_context, graph, receiver]
  5. Evaluate on the test slice and write models/yogii_risk_model.json + models/metrics.json

Same seed, same data, same artifact. The data is synthetic: the metrics say
how well the model recovers the synthetic labels, nothing about real fraud.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import synthetic  # noqa: E402
from xgb_numpy import NumpyXGBClassifier  # noqa: E402

SEED = synthetic.SEED
PARAMS = {
    "objective": "binary:logistic",
    "n_estimators": 60,
    "max_depth": 3,
    "eta": 0.2,
    "lambda": 1.0,
    "gamma": 0.0,
    "subsample": 0.8,
    "tree_method": "hist",
    "max_bin": 32,
    "scale_pos_weight_cap": 4.0,
    "seed": SEED,
}
COMPONENTS = {
    "amount": (synthetic.AMOUNT_FEATURES, "label_amount"),
    "behavior": (synthetic.BEHAVIOR_FEATURES, "label_behavior"),
    "context": (synthetic.CONTEXT_FEATURES, "label_context"),
}
BANDS = [
    {"name": "LOW", "min": 0, "max": 29},
    {"name": "MEDIUM", "min": 30, "max": 59},
    {"name": "HIGH", "min": 60, "max": 84},
    {"name": "VERY_HIGH", "min": 85, "max": 100},
]


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def predict_browser(comp, X):
    """Score with the exported browser format (float32 compare, like the browser)."""
    X = np.asarray(X, dtype=np.float32)
    b = comp["base_score"]
    margin = np.full(len(X), math.log(b / (1 - b)))
    for tree in comp["trees"]:
        nodes = tree["nodes"]
        stack = [(0, np.arange(len(X)))]
        while stack:
            k, idx = stack.pop()
            nd = nodes[k]
            if "v" in nd:
                margin[idx] += nd["v"]
                continue
            left = X[idx, nd["f"]] < np.float32(nd["t"])
            stack.append((nd["l"], idx[left]))
            stack.append((nd["r"], idx[~left]))
    return sigmoid(margin)


def pr_auc(y, s):
    """Average precision (area under the precision-recall curve, step-wise)."""
    y = np.asarray(y)
    order = np.argsort(-np.asarray(s), kind="mergesort")
    y = y[order]
    tp = np.cumsum(y)
    k = np.arange(1, len(y) + 1)
    precision = tp / k
    pos = y.sum()
    if pos == 0:
        return 0.0
    return float((precision * y).sum() / pos)


def pick_engine(name):
    if name in ("auto", "xgboost"):
        try:
            import xgboost  # noqa: F401
            return "xgboost"
        except ImportError:
            if name == "xgboost":
                sys.exit("ERROR: --engine xgboost was requested but the 'xgboost' package is not "
                         "installed. Install it with: pip install xgboost  (or use --engine numpy)")
    return "numpy"


def train_component(engine, X, y, spw):
    if engine == "xgboost":
        import xgboost as xgb
        from export_xgboost import convert_booster
        dtrain = xgb.DMatrix(X, label=y)
        params = {
            "objective": "binary:logistic", "max_depth": PARAMS["max_depth"], "eta": PARAMS["eta"],
            "lambda": PARAMS["lambda"], "gamma": PARAMS["gamma"], "subsample": PARAMS["subsample"],
            "tree_method": "hist", "max_bin": PARAMS["max_bin"], "scale_pos_weight": spw,
            "seed": SEED, "nthread": 1, "verbosity": 0,
        }
        booster = xgb.train(params, dtrain, num_boost_round=PARAMS["n_estimators"])
        return convert_booster(booster), booster
    clf = NumpyXGBClassifier(n_estimators=PARAMS["n_estimators"], max_depth=PARAMS["max_depth"],
                             eta=PARAMS["eta"], reg_lambda=PARAMS["lambda"], gamma=PARAMS["gamma"],
                             subsample=PARAMS["subsample"], max_bin=PARAMS["max_bin"],
                             scale_pos_weight=spw, seed=SEED)
    clf.fit(np.asarray(X, dtype=np.float32).astype(float), y)
    return clf.to_browser(), None


def fmt_num(x):
    x = float(x)
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return repr(x)


def dump_model(model, path):
    """Readable JSON: one tree per line so git diffs stay reviewable."""
    comps = model.pop("components")
    text = json.dumps(model, indent=2)
    assert text.endswith("}")
    parts = []
    for name, comp in comps.items():
        lines = [f'    "{name}": {{', f'      "base_score": {fmt_num(comp["base_score"])},',
                 f'      "features": {json.dumps(comp["features"])},', '      "trees": [']
        tree_lines = []
        for t in comp["trees"]:
            nodes = []
            for nd in t["nodes"]:
                if "v" in nd:
                    nodes.append('{"v":%s}' % fmt_num(nd["v"]))
                else:
                    nodes.append('{"f":%d,"t":%s,"l":%d,"r":%d}' % (nd["f"], fmt_num(nd["t"]), nd["l"], nd["r"]))
            tree_lines.append("        [" + ",".join(nodes) + "]")
        lines.append(",\n".join(tree_lines))
        lines.append("      ]")
        lines.append("    }")
        parts.append("\n".join(lines))
    text = text[:-2] + ',\n  "components": {\n' + ",\n".join(parts) + "\n  }\n}\n"
    model["components"] = comps
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["auto", "xgboost", "numpy"], default="auto")
    ap.add_argument("--rows", type=int, default=24000)
    ap.add_argument("--out", default=os.path.join(ROOT, "models"))
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "synthetic_transactions.csv"))
    args = ap.parse_args(argv)

    engine = pick_engine(args.engine)
    print(f"[train] engine: {engine}")

    os.makedirs(os.path.dirname(args.data), exist_ok=True)
    synthetic.write_csv(synthetic.generate(args.rows, SEED), args.data)
    with open(args.data, "rb") as fh:
        data_sha = hashlib.sha256(fh.read()).hexdigest()
    data = synthetic.read_csv(args.data)
    n = len(data["tx_id"])
    i_tr, i_va = int(n * 0.70), int(n * 0.85)
    sl = {"train": slice(0, i_tr), "validation": slice(i_tr, i_va), "test": slice(i_va, n)}
    print(f"[train] {n} synthetic rows: train {i_tr}, validation {i_va - i_tr}, test {n - i_va}")

    comps, probs, comp_metrics = {}, {}, {}
    native_dir = os.path.join(args.out, "native")
    os.makedirs(native_dir, exist_ok=True)
    engine_version = "numpy (ml/xgb_numpy.py)"
    for name, (feats, label) in COMPONENTS.items():
        X = np.column_stack([data[f] for f in feats])
        y = data[label].astype(int)
        ytr = y[sl["train"]]
        pos = max(int(ytr.sum()), 1)
        spw = float(min(PARAMS["scale_pos_weight_cap"], (len(ytr) - pos) / pos))
        comp, booster = train_component(engine, X[sl["train"]], ytr, spw)
        if booster is not None:
            import xgboost as xgb
            engine_version = f"xgboost {xgb.__version__}"
            booster.save_model(os.path.join(native_dir, f"{name}.json"))
            direct = booster.predict(xgb.DMatrix(X[sl["test"]]))
            mine = predict_browser(comp, X[sl["test"]])
            gap = float(np.max(np.abs(direct - mine)))
            print(f"[train] {name}: exported trees match xgboost (max |diff| = {gap:.2e})")
            if gap > 1e-4:
                sys.exit(f"ERROR: exported {name} model disagrees with xgboost (max diff {gap})")
        comp["features"] = feats
        comps[name] = comp
        probs[name] = predict_browser(comp, X)
        comp_metrics[name] = {
            "label": label,
            "scale_pos_weight": round(spw, 4),
            "positive_rate_train": round(float(ytr.mean()), 4),
            "pr_auc_test": round(pr_auc(y[sl["test"]], probs[name][sl["test"]]), 4),
        }
        print(f"[train] {name}: PR-AUC (test) {comp_metrics[name]['pr_auc_test']}")

    # Linear-regression stacker fitted on the validation slice
    Z = np.column_stack([probs["amount"], probs["behavior"], probs["context"],
                         data["graph_score"], data["receiver_score"]])
    rating = data["analyst_rating"]
    Zv = np.column_stack([np.ones(i_va - i_tr), Z[sl["validation"]]])
    coef, *_ = np.linalg.lstsq(Zv, rating[sl["validation"]], rcond=None)
    intercept, weights = float(coef[0]), [float(w) for w in coef[1:]]

    def r2(s):
        pred = coef[0] + Z[s] @ coef[1:]
        yy = rating[s]
        return 1 - float(((yy - pred) ** 2).sum() / ((yy - yy.mean()) ** 2).sum())

    score = np.clip(coef[0] + Z @ coef[1:], 0, 1) * 100
    st = score[sl["test"]]
    yt = data["is_fraud"][sl["test"]].astype(int)
    pred = st >= 60
    tp = int((pred & (yt == 1)).sum()); fp = int((pred & (yt == 0)).sum())
    fn = int((~pred & (yt == 1)).sum()); tn = int((~pred & (yt == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    bands = {b["name"]: int(((st >= b["min"]) & (st < b["max"] + 1)).sum()) for b in BANDS}

    metrics = {
        "WARNING": "Synthetic data only. These numbers measure how well the model recovers "
                   "synthetic labels. They are not real-world fraud performance.",
        "engine": engine_version,
        "seed": SEED,
        "rows": {"total": n, "train": i_tr, "validation": i_va - i_tr, "test": n - i_va},
        "split": "time-based 70/15/15",
        "data_sha256": data_sha,
        "test": {
            "positive_definition": "synthetic analyst rating >= 0.6",
            "decision_threshold": "score >= 60 (HIGH or VERY_HIGH)",
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "pr_auc": round(pr_auc(yt, st), 4),
            "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "band_counts": bands,
        },
        "components": comp_metrics,
        "stacker": {
            "type": "linear regression (least squares)",
            "fit_on": "validation slice",
            "target": "synthetic analyst risk rating (0-1)",
            "inputs": ["p_amount", "p_behavior", "p_context", "graph", "receiver"],
            "intercept": round(intercept, 6),
            "weights": [round(w, 6) for w in weights],
            "r2_validation": round(r2(sl["validation"]), 4),
            "r2_test": round(r2(sl["test"]), 4),
        },
        "params": PARAMS,
    }

    model = {
        "format": "yogii-risk-model",
        "version": "1.0.0",
        "synthetic": True,
        "notice": "Trained on synthetic data only. Prototype thresholds, not RBI, NPCI or bank standards.",
        "engine": engine_version,
        "seed": SEED,
        "data_sha256": data_sha,
        "compare": "float32",
        "features": {k: v[0] for k, v in COMPONENTS.items()},
        "stacker": {
            "inputs": ["p_amount", "p_behavior", "p_context", "graph", "receiver"],
            "intercept": intercept,
            "weights": weights,
            "r2": round(r2(sl["validation"]), 4),
        },
        "bands": BANDS,
        "graph": {"max_hops": 3, "window_minutes": 120, "amount_tolerance": 0.25,
                  "hop_factor": synthetic.HOP_FACTOR, "indirect_days": 90},
        "receiver": {"watchlist": 1.0, "unregistered": 0.25, "new_account": 0.2, "new_account_days": 7,
                     "many_payers": 0.25, "many_payers_count": 3, "pass_through": 0.3,
                     "pass_through_ratio": 0.7, "levels": {"elevated": 0.3, "high": 0.6}},
        "summary": {"precision": metrics["test"]["precision"], "recall": metrics["test"]["recall"],
                    "pr_auc": metrics["test"]["pr_auc"], "stacker_r2": metrics["stacker"]["r2_test"]},
        "components": comps,
    }
    os.makedirs(args.out, exist_ok=True)
    dump_model(model, os.path.join(args.out, "yogii_risk_model.json"))
    with open(os.path.join(args.out, "metrics.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(metrics, fh, indent=2)
        fh.write("\n")
    print(f"[train] stacker: intercept {intercept:.4f}, weights {[round(w, 4) for w in weights]}, "
          f"R2 val {metrics['stacker']['r2_validation']} test {metrics['stacker']['r2_test']}")
    print(f"[train] test: precision {precision:.3f} recall {recall:.3f} F1 {f1:.3f} "
          f"PR-AUC {metrics['test']['pr_auc']}")
    print("[train] wrote models/yogii_risk_model.json and models/metrics.json")


if __name__ == "__main__":
    main()
