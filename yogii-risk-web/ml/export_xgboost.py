"""Convert real xgboost boosters into the Yogii browser tree format.

Browser format per component:
    {"base_score": p0, "trees": [{"nodes": [...]}, ...]}
Nodes are {"f": feature_index, "t": threshold, "l": left_id, "r": right_id}
or {"v": leaf_value}. x < t goes left. Leaf values already include eta.
margin = logit(base_score) + sum(leaf values); probability = sigmoid(margin).

Works on the JSON dump that `Booster.save_raw("json")` / `save_model("x.json")`
produces. `base_score` may be stored as "5E-1" or, in newer xgboost, "[5E-1]".
"""

from __future__ import annotations

import json


def parse_base_score(raw) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].split(",")[0].strip()
    return float(s)


def convert_tree(tree: dict) -> dict:
    left = tree["left_children"]
    right = tree["right_children"]
    feat = tree["split_indices"]
    cond = tree["split_conditions"]
    nodes = []
    for i in range(len(left)):
        if left[i] == -1:
            nodes.append({"v": float(cond[i])})
        else:
            nodes.append({"f": int(feat[i]), "t": float(cond[i]), "l": int(left[i]), "r": int(right[i])})
    return {"nodes": nodes}


def convert_model_json(model: dict) -> dict:
    learner = model["learner"]
    base = parse_base_score(learner["learner_model_param"]["base_score"])
    trees = learner["gradient_booster"]["model"]["trees"]
    return {"base_score": base, "trees": [convert_tree(t) for t in trees]}


def convert_booster(booster) -> dict:
    raw = booster.save_raw(raw_format="json")
    return convert_model_json(json.loads(bytes(raw).decode("utf-8")))


def convert_file(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return convert_model_json(json.load(fh))


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        out = convert_file(p)
        print(p, "->", len(out["trees"]), "trees, base_score", out["base_score"])
