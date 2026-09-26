"""Build dist/index.html: one self-contained page with styles, model and app inlined.

    python scripts/build.py

The output is deterministic (no timestamps), so rebuilding an unchanged tree
leaves `git status` clean. The build fails if the model file is missing:
the app never ships without its model.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
MODEL = os.path.join(ROOT, "models", "yogii_risk_model.json")
OUT = os.path.join(ROOT, "dist", "index.html")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n")


def sha256_b64(text):
    return base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


def main():
    if not os.path.exists(MODEL):
        sys.exit(f"ERROR: model file missing: {MODEL}\nRun `python ml/train.py` first.")
    html = read(os.path.join(SRC, "index.html"))
    css = read(os.path.join(SRC, "styles.css"))
    app = read(os.path.join(SRC, "app.js"))
    model = json.loads(read(MODEL))  # validates JSON
    if model.get("format") != "yogii-risk-model":
        sys.exit("ERROR: models/yogii_risk_model.json is not a Yogii risk model")
    if "</script" in app.lower():
        sys.exit("ERROR: src/app.js must not contain a closing script tag")

    # Compact JSON inside the page; "</" is escaped so the data can't end the tag.
    model_text = json.dumps(model, separators=(",", ":")).replace("</", "<\\/")
    csp = ("default-src 'none'; script-src 'sha256-%s'; style-src 'unsafe-inline'; img-src data:; "
           "connect-src 'none'; base-uri 'none'; form-action 'none'" % sha256_b64(app))

    replacements = [
        ('<link rel="stylesheet" href="styles.css">', "<style>\n" + css + "</style>"),
        ('<script id="yogii-model" type="application/json" data-src="../models/yogii_risk_model.json"></script>',
         '<script id="yogii-model" type="application/json">' + model_text + "</script>"),
        ('<script src="app.js"></script>', "<script>" + app + "</script>"),
        ('<meta charset="utf-8">', '<meta charset="utf-8">\n<meta http-equiv="Content-Security-Policy" content="' + csp + '">'),
    ]
    for old, new in replacements:
        if html.count(old) != 1:
            sys.exit(f"ERROR: expected exactly one {old!r} in src/index.html")
        html = html.replace(old, new)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    size = os.path.getsize(OUT)
    print(f"[build] wrote dist/index.html ({size / 1024:.0f} KB, model {model['version']}, {model['engine']})")


if __name__ == "__main__":
    main()
