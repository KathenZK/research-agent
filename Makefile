.PHONY: verify test

PYTHON ?= python3

verify test:
	$(PYTHON) -m unittest discover -s tests -v
