# Yogii Risk Web. Everything here is simulated; see README.md.
PYTHON ?= python
NODE ?= node

.PHONY: all train train-numpy scenarios build test e2e serve check clean-check

all: build

train:
	$(PYTHON) ml/train.py

train-numpy:
	$(PYTHON) ml/train.py --engine numpy

scenarios:
	$(PYTHON) ml/check_scenarios.py

build:
	$(PYTHON) scripts/build.py

test:
	$(NODE) --test tests/engine.test.js

e2e: build
	$(PYTHON) tests/e2e_test.py

serve: build
	$(PYTHON) -m http.server -d dist 8080

# Every acceptance check, in order
check: train scenarios build test e2e

# check, then confirm the rebuild left no changes behind
clean-check: check
	git diff --exit-code -- . && echo "git tree clean after rebuild"
