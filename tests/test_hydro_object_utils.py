"""
Test script for HydroObjectUtilsV2.

This script demonstrates how to use the HydroObjectUtilsV2 utility class
to load and parse water network topology objects from YAML configuration files.

Usage:
    python tests/test_hydro_object_utils.py
"""

import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from hydros_agent_sdk.utils import (
    HydroObjectUtilsV2,
    WaterwayTopology,
    TopHydroObject,
    SimpleChildObject,
    HydroObjectType,
    MetricsCodes,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("HydroObjectUtilsTest")


def test_basic_loading():
    """Test basic topology loading without parameters."""
    logger.info("="*70)
    logger.info("Test 1: Basic Topology Loading")
    logger.info("="*70)

    # Example URL (replace with actual URL)
    modeling_url = "http://47.97.1.45:9000/hydros/京石段/modelingV2/objects.yaml"

    try:
        topology = HydroObjectUtilsV2.build_waterway_topology(modeling_url)

        logger.info(f"✓ Successfully loaded topology")
        logger.info(f"  - Top-level objects: {len(topology.top_objects)}")
        logger.info(f"  - Child-to-parent mappings: {len(topology.child_to_parent_map)}")
        logger.info(f"  - Upstream connections: {len(topology.upstream_map)}")
        logger.info(f"  - Downstream connections: {len(topology.downstream_map)}")

        return topology
    except Exception as e:
        logger.error(f"✗ Failed to load topology: {e}")
        return None


def test_with_parameters():
    """Test topology loading with specific parameters."""
    logger.info("="*70)
    logger.info("Test 2: Loading with Specific Parameters")
    logger.info("="*70)

    modeling_url = "http://47.97.1.45:9000/hydros/京石段/modelingV2/objects.yaml"

    # Specify which parameters to load
    param_keys = {'max_opening', 'min_opening', 'interpolate_cross_section_count'}

    try:
        topology = HydroObjectUtilsV2.build_waterway_topology(
            modeling_yml_uri=modeling_url,
            param_keys=param_keys,
            with_metrics_code=False
        )

        logger.info(f"✓ Successfully loaded topology with filtered parameters")
        logger.info(f"  - Requested parameters: {param_keys}")

        # Show first object's parameters
        if topology.top_objects:
            first_obj = topology.top_objects[0]
            logger.info(f"  - First object: {first_obj.object_name}")
            logger.info(f"    Parameters: {list(first_obj.params.keys())}")

        return topology
    except Exception as e:
        logger.error(f"✗ Failed to load topology: {e}")
        return None


def test_with_metrics():
    """Test topology loading with metrics codes."""
    logger.info("="*70)
    logger.info("Test 3: Loading with Metrics Codes")
    logger.info("="*70)

    modeling_url = "http://47.97.1.45:9000/hydros/京石段/modelingV2/objects.yaml"

    param_keys = {'max_opening'}

    try:
        topology = HydroObjectUtilsV2.build_waterway_topology(
            modeling_yml_uri=modeling_url,
            param_keys=param_keys,
            with_metrics_code=True
        )

        logger.info(f"✓ Successfully loaded topology with metrics codes")

        # Show metrics for child objects
        metrics_count = 0
        for top_obj in topology.top_objects:
            for child in top_obj.children:
                if child.metrics:
                    metrics_count += 1
                    if metrics_count <= 3:  # Show first 3
                        logger.info(f"  - {child.object_name} ({child.object_type}): "
                                  f"metrics={child.metrics}")

        logger.info(f"  - Total children with metrics: {metrics_count}")

        return topology
    except Exception as e:
        logger.error(f"✗ Failed to load topology: {e}")
        return None


def test_topology_queries(topology: WaterwayTopology):
    """Test topology query methods."""
    logger.info("="*70)
    logger.info("Test 4: Topology Query Methods")
    logger.info("="*70)

    if not topology or not topology.top_objects:
        logger.warning("No topology available for testing")
        return

    # Test 1: Get top object by ID
    first_obj = topology.top_objects[0]
    obj_id = first_obj.object_id

    retrieved_obj = topology.get_top_object(obj_id)
    if retrieved_obj:
        logger.info(f"✓ get_top_object({obj_id}): {retrieved_obj.object_name}")

    # Test 2: Get object (including children)
    if first_obj.children:
        child = first_obj.children[0]
        child_id = child.object_id

        retrieved_child = topology.get_object(child_id)
        if retrieved_child:
            logger.info(f"✓ get_object({child_id}): {retrieved_child.object_name}")

    # Test 3: Get parent by child ID
    if first_obj.children:
        child_id = first_obj.children[0].object_id
        parent = topology.get_top_object_by_child_id(child_id)
        if parent:
            logger.info(f"✓ get_top_object_by_child_id({child_id}): {parent.object_name}")

    # Test 4: Check if object is child
    if first_obj.children:
        child_id = first_obj.children[0].object_id
        is_child = topology.is_child_object(child_id)
        logger.info(f"✓ is_child_object({child_id}): {is_child}")

    # Test 5: Find neighbors
    neighbors = topology.find_neighbors(obj_id)
    logger.info(f"✓ find_neighbors({obj_id}):")
    logger.info(f"    Upstream: {neighbors['upstream']}")
    logger.info(f"    Downstream: {neighbors['downstream']}")

    # Test 6: Filter objects
    filtered = topology.get_objects(
        agent_managed_top_object_ids={obj_id},
        child_object_types={'CrossSection', 'Gate'}
    )
    logger.info(f"✓ get_objects (filtered): {len(filtered)} objects")


def test_object_iteration(topology: WaterwayTopology):
    """Test iterating through topology objects."""
    logger.info("="*70)
    logger.info("Test 5: Object Iteration")
    logger.info("="*70)

    if not topology:
        logger.warning("No topology available for testing")
        return

    # Count objects by type
    type_counts = {}
    child_type_counts = {}

    for top_obj in topology.top_objects:
        obj_type = top_obj.object_type
        type_counts[obj_type] = type_counts.get(obj_type, 0) + 1

        for child in top_obj.children:
            child_type = child.object_type
            child_type_counts[child_type] = child_type_counts.get(child_type, 0) + 1

    logger.info("Top-level object types:")
    for obj_type, count in sorted(type_counts.items()):
        logger.info(f"  - {obj_type}: {count}")

    logger.info("Child object types:")
    for child_type, count in sorted(child_type_counts.items()):
        logger.info(f"  - {child_type}: {count}")


def test_convenience_method():
    """Test the convenience from_url method."""
    logger.info("="*70)
    logger.info("Test 6: Convenience Method (from_url)")
    logger.info("="*70)

    modeling_url = "http://47.97.1.45:9000/hydros/京石段/modelingV2/objects.yaml"

    try:
        # This is the simplest way to load topology
        topology = HydroObjectUtilsV2.from_url(modeling_url)

        logger.info(f"✓ Successfully loaded topology using from_url()")
        logger.info(f"  - Top-level objects: {len(topology.top_objects)}")

        return topology
    except Exception as e:
        logger.error(f"✗ Failed to load topology: {e}")
        return None


def main():
    """Run all tests."""
    logger.info("Starting HydroObjectUtilsV2 tests...")
    logger.info("")

    # Test 1: Basic loading
    topology1 = test_basic_loading()
    logger.info("")

    # Test 2: With parameters
    topology2 = test_with_parameters()
    logger.info("")

    # Test 3: With metrics
    topology3 = test_with_metrics()
    logger.info("")

    # Test 4: Query methods (use topology from test 3)
    if topology3:
        test_topology_queries(topology3)
        logger.info("")

    # Test 5: Object iteration
    if topology3:
        test_object_iteration(topology3)
        logger.info("")

    # Test 6: Convenience method
    topology6 = test_convenience_method()
    logger.info("")

    logger.info("="*70)
    logger.info("All tests completed!")
    logger.info("="*70)


if __name__ == "__main__":
    main()
