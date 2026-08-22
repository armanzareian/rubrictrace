.PHONY: test quality demo eval metrics sarif

PYTHON ?= python3

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

quality:
	$(PYTHON) scripts/quality.py

demo:
	PYTHONPATH=src $(PYTHON) -m rubrictrace audit \
		--records examples/judgments/records.jsonl \
		--policy examples/judgments/policy.json \
		--fail-on critical

eval:
	PYTHONPATH=src $(PYTHON) -m rubrictrace eval \
		--suite examples/judgments/suite.json

metrics:
	PYTHONPATH=src $(PYTHON) -m rubrictrace metrics \
		--records examples/judgments/records.jsonl \
		--policy examples/judgments/policy.json

sarif:
	PYTHONPATH=src $(PYTHON) -m rubrictrace audit \
		--records examples/judgments/records.jsonl \
		--policy examples/judgments/policy.json \
		--format sarif \
		--fail-on critical
