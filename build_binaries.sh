#!/bin/bash
set -e

# Ensure PyInstaller is installed
if ! command -v pyinstaller &> /dev/null; then
    echo "PyInstaller not found. Installing..."
    pip install pyinstaller
fi

echo "Building Linux binary..."
pyinstaller --onefile run_cli.py --name hydros-sum-linux --clean

echo "Build complete. Binary located at dist/hydros-sum-linux"
