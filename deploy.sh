#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO] $1${NC}"
}

log_error() {
    echo -e "${RED}[ERROR] $1${NC}"
}

# Configuration
REPO_URL="https://packages.aliyun.com/68f338b0e6c3e0425dbd04c4/pypi/hydros-agent-sdk"
USERNAME="68f3388e46600729fe9b3afa"
# NOTE: It is recommended to use environment variables or ~/.pypirc for passwords.
# Using the provided token for convenience as requested.
PASSWORD="SQOO6m=WpwD_"

# 1. Clean
log_info "Step 1/3: Cleaning up old build artifacts..."
rm -rf dist build *.egg-info
if [ $? -eq 0 ]; then
    log_info "Cleanup successful."
else
    log_error "Cleanup failed."
    exit 1
fi

# 2. Build
log_info "Step 2/3: Building package..."
# Ensure we use the workspace python
PYTHON_EXEC="./.venv/bin/python"
if [ ! -f "$PYTHON_EXEC" ]; then
    log_info "Virtual environment python not found at $PYTHON_EXEC, trying 'python3'..."
    PYTHON_EXEC="python3"
fi

$PYTHON_EXEC -m build
if [ $? -eq 0 ]; then
    log_info "Build successful."
else
    log_error "Build failed."
    exit 1
fi

# 3. Upload
log_info "Step 3/3: Uploading wheel to registry..."
# Note: Uploading only *.whl to avoid Aliyun registry conflict bug with sdist
twine upload --repository-url "$REPO_URL" -u "$USERNAME" -p "$PASSWORD" dist/*.whl

if [ $? -eq 0 ]; then
    log_info "Upload successful!"
    log_info "Deployment complete."
else
    log_error "Upload failed."
    exit 1
fi
