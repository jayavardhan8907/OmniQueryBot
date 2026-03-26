# Python Virtual Environments FAQ

## Why use a virtual environment?

A virtual environment keeps project dependencies isolated from the global Python installation. This makes it easier to reproduce setups, avoid package version conflicts, and explain the environment to other developers during onboarding or handoff.

## How do I create a virtual environment on Windows?

Use Python 3.11 for this project because the local machine already has it installed and most machine learning packages work more reliably on Python 3.11 than on Python 3.14. From the project root, run `py -3.11 -m venv .venv`. Then activate the environment with `.\.venv\Scripts\activate`. After activation, install dependencies with `uv sync --python 3.11 --extra dev` or use `pip install -e .[dev]` if you prefer plain pip.

## How do I know the right interpreter is active?

Run `python --version` and confirm the output shows Python 3.11.x. You can also run `where python` in PowerShell to verify that the active interpreter is coming from the `.venv\Scripts` directory instead of the global install.

## When should I recreate the environment?

Recreate the virtual environment when dependencies are badly out of sync, when native packages fail after a Python upgrade, or when the lockfile changes in a way that causes import errors. Deleting `.venv` and creating it again is often faster than debugging a corrupted local setup.
