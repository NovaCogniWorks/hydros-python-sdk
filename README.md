# Hydros SDK

A sample project demonstrating a simple sum function, PyPI packaging, and binary executable generation for Linux and Windows.

## Installation from PyPI

```bash
pip install hydros-sdk
```

## Usage

### Python Library
```python
from hydros_sdk import calc_sum

print(calc_sum(1, 2))  # Output: 3
```

### CLI
If installed via pip:
```bash
hydros-sum 1 2
```

Or from source:
```bash
python -m hydros_sdk.cli 1 2
```

## Building Binaries

This project uses `PyInstaller` to generate standalone executables.

### Linux
Run the build script:
```bash
./build_binaries.sh
```
The executable will be in `dist/hydros-sum-linux`.

### Windows
Run the following command in PowerShell or Command Prompt:
```cmd
pyinstaller --onefile run_cli.py --name hydros-sum-windows
```
The executable will be in `dist/hydros-sum-windows.exe`.
