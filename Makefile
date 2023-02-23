EDULINT_PATH = $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
EDULINT_VENV_PATH = ${EDULINT_PATH}/.venv

DATA_PATH = ${EDULINT_PATH}../data
LINTINGS_PATH = ${EDULINT_PATH}../lintings

.PHONY: all dist mypy test check run setup clean venv_create

all: setup venv_create dist check

setup: requirements.dev.txt
	python3 -m pip install --user -r requirements.dev.txt

venv_create: requirements.txt
	python3 -m venv ${EDULINT_VENV_PATH}
	. ${EDULINT_VENV_PATH}/bin/activate
	python3 -m pip install -r requirements.txt

clean:
	rm -rf __pycache__ edulint.egg-info .mypy_cache .venv dist

dist:
	python3 -m build ${EDULINT_PATH}
	. ${EDULINT_VENV_PATH}/bin/activate && \
		python3 -m pip install --upgrade ${EDULINT_PATH}

mypy:
	export MYPYPATH=${EDULINT_PATH} && \
		mypy ${EDULINT_PATH}/edulint --strict && \
		mypy ${EDULINT_PATH}/tests/*.py

test:
	. ${EDULINT_VENV_PATH}/bin/activate && \
		export PYTHONPATH=${EDULINT_PATH} && \
		python3 -m pytest -n4 -k "${ARGS}" ${EDULINT_PATH}/tests/

check: mypy test

run:
	export PYTHONPATH=${EDULINT_PATH} && \
		python3 -m edulint ${ARGS}

lint_data:
	export DATA_DIR=${DATA_PATH}/${YEAR}; \
	export LINTINGS_DIR=${LINTINGS_PATH}/${YEAR}/edulint-${VERSION}; \
	mkdir -p $$LINTINGS_DIR; \
	for week in `ls $$DATA_DIR`; do \
		echo $$week; \
		export PYTHONPATH=${EDULINT_PATH} && \
			python3 -m edulint $$DATA_DIR/$$week/*.py > $$LINTINGS_DIR/$$week.txt; \
		export PYTHONPAT=${EDULINT_PATH} && \
			python3 -m edulint --json $$DATA_DIR/$$week/*.py > $$LINTINGS_DIR/$$week.json; \
	done;

