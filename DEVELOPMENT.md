# Developer Guide for Hydros Python SDK

Welcome to the Hydros Python SDK! This guide will help you set up your development environment, run tests, and build the project.

## 1. Prerequisites

- **Python**: Version 3.9 or higher is required.
- **Git**: To clone the repository.

## 2. Environment Setup

It is highly recommended to use a virtual environment to manage dependencies.

### Step 1: Clone the repository
```bash
git clone https://github.com/StartDt/hydros-python-sdk.git
cd hydros-python-sdk
```

### Step 2: Create a Virtual Environment

**Linux/macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows:**
```bash
python -m venv .venv
.venv\Scripts\activate
```

You should see `(.venv)` in your terminal prompt.

## 3. Install Dependencies

### Install Project Dependencies (Editable Mode)
Installing in editable mode allows you to make changes to the code and see them immediately without reinstalling.

```bash
pip install -e .
```

### Install Development Tools
You will need additional tools for testing, building, and publishing the package.

```bash
pip install pytest build twine
```

## 4. Running Tests

We use `pytest` for testing.

```bash
pytest
```

## 5. Building the Package

To build the source distribution and wheel:

```bash
python -m build
```

This will create a `dist/` directory containing the `.tar.gz` and `.whl` files.

## 6. Deployment (Maintainers Only)

A `deploy.sh` script is provided to automate the clean, build, and upload process.

```bash
./deploy.sh
```

**Note**: The deployment script is configured for the project's PyPI registry. Ensure you have the necessary credentials configured or passed as environment variables if you are a maintainer.

## 7. Project Structure

- `hydros_agent_sdk/`: Source code for the SDK.
- `tests/`: Unit and integration tests.
- `pyproject.toml`: Project configuration and dependencies.
- `deploy.sh`: Deployment script.
- `README.md`: User-facing documentation.
