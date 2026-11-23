# Offline gate. No API key. `make check` recomputes the README numbers.
.PHONY: test eval check

test:
	python3 -m pytest tests/ -o addopts="" -q

eval:
	python3 eval/run_cases.py

check: test eval
	python3 eval/run_cases.py --selftest
	python3 eval/recompute_stored_run.py --selftest
