.DEFAULT_GOAL := help
.PHONY: help install run test build clean

PYTHON ?= python3
VENV_PYTHON := .venv/bin/python

help:
	@echo "make install - Create .venv and install dependencies"
	@echo "make run     - Launch the desktop app"
	@echo "make test    - Run offline tests"
	@echo "make build   - Test and build Linux executable in dist/InstaUploader"
	@echo "make clean   - Remove Python caches and build outputs (build, dist)"

install:
	"$(PYTHON)" -m venv .venv
	"$(VENV_PYTHON)" -m pip install -r requirements.txt

run:
	"$(VENV_PYTHON)" main.py

test:
	"$(VENV_PYTHON)" -m unittest discover -s tests -v

build: test
	"$(VENV_PYTHON)" -m PyInstaller --noconfirm --clean --onefile --windowed --name InstaUploader --collect-data PySide6 main.py

clean:
	find . -type d \( -name .venv -o -name .git \) -prune -o -type d -name __pycache__ -prune -exec rm -rf {} + -o -type f \( -name '*.pyc' -o -name '*.pyo' \) -exec rm -f {} +
	rm -rf build dist
