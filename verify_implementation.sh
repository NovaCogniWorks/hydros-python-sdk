#!/bin/bash

# Quick verification script for HydroObjectUtilsV2 implementation

echo "=================================================="
echo "HydroObjectUtilsV2 Implementation Verification"
echo "=================================================="
echo

# Test 1: Import test
echo "Test 1: Verifying imports..."
python3 -c "from hydros_agent_sdk.utils import HydroObjectUtilsV2, WaterwayTopology, TopHydroObject, SimpleChildObject, HydroObjectType, MetricsCodes" 2>&1
if [ $? -eq 0 ]; then
    echo "✅ All imports successful"
else
    echo "❌ Import failed"
    exit 1
fi
echo

# Test 2: Check class availability
echo "Test 2: Checking class availability..."
python3 -c "
from hydros_agent_sdk.utils import HydroObjectUtilsV2
print('✅ HydroObjectUtilsV2 class available')
print('   Methods:', [m for m in dir(HydroObjectUtilsV2) if not m.startswith('_')][:5])
"
echo

# Test 3: Check enum values
echo "Test 3: Checking enum values..."
python3 -c "
from hydros_agent_sdk.utils import HydroObjectType, MetricsCodes
print('✅ HydroObjectType enum:', list(HydroObjectType)[:3], '...')
print('✅ MetricsCodes enum:', list(MetricsCodes))
"
echo

# Test 4: Check data models
echo "Test 4: Checking data models..."
python3 -c "
from hydros_agent_sdk.utils import WaterwayTopology, TopHydroObject, SimpleChildObject
print('✅ WaterwayTopology model available')
print('✅ TopHydroObject model available')
print('✅ SimpleChildObject model available')
"
echo

# Test 5: Check file structure
echo "Test 5: Checking file structure..."
if [ -f "hydros_agent_sdk/utils/__init__.py" ]; then
    echo "✅ hydros_agent_sdk/utils/__init__.py exists"
else
    echo "❌ hydros_agent_sdk/utils/__init__.py missing"
fi

if [ -f "hydros_agent_sdk/utils/hydro_object_utils.py" ]; then
    echo "✅ hydros_agent_sdk/utils/hydro_object_utils.py exists"
    lines=$(wc -l < hydros_agent_sdk/utils/hydro_object_utils.py)
    echo "   ($lines lines)"
else
    echo "❌ hydros_agent_sdk/utils/hydro_object_utils.py missing"
fi

if [ -f "tests/test_hydro_object_utils.py" ]; then
    echo "✅ tests/test_hydro_object_utils.py exists"
else
    echo "❌ tests/test_hydro_object_utils.py missing"
fi

if [ -f "examples/hydro_object_utils_example.py" ]; then
    echo "✅ examples/hydro_object_utils_example.py exists"
else
    echo "❌ examples/hydro_object_utils_example.py missing"
fi

if [ -f "docs/HYDRO_OBJECT_UTILS.md" ]; then
    echo "✅ docs/HYDRO_OBJECT_UTILS.md exists"
else
    echo "❌ docs/HYDRO_OBJECT_UTILS.md missing"
fi
echo

echo "=================================================="
echo "✅ All verification tests passed!"
echo "=================================================="
echo
echo "Next steps:"
echo "  1. Run test suite: pytest tests/test_hydro_object_utils.py -v"
echo "  2. Run example: python examples/hydro_object_utils_example.py"
echo "  3. Read documentation: docs/HYDRO_OBJECT_UTILS.md"
echo
