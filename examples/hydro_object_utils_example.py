"""
Simple example demonstrating HydroObjectUtilsV2 usage.

This example shows how to load water network topology objects from a YAML file
and access the topology information.
"""

import logging
from hydros_agent_sdk.utils import HydroObjectUtilsV2

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Demonstrate basic usage of HydroObjectUtilsV2."""

    # Example 1: Load topology with default settings
    logger.info("Example 1: Load topology with default settings")
    logger.info("="*60)

    modeling_url = "http://47.97.1.45:9000/hydros/京石段/modelingV2/objects.yaml"

    try:
        # Simplest way to load topology
        topology = HydroObjectUtilsV2.from_url(modeling_url)

        logger.info(f"✓ Loaded {len(topology.top_objects)} top-level objects")

        # Show first few objects
        for i, obj in enumerate(topology.top_objects[:5]):
            logger.info(f"  {i+1}. {obj.object_name} ({obj.object_type})")
            logger.info(f"     - Children: {len(obj.children)}")
            logger.info(f"     - Parameters: {list(obj.params.keys())}")

    except Exception as e:
        logger.error(f"✗ Failed to load topology: {e}")
        return

    print()

    # Example 2: Load with specific parameters
    logger.info("Example 2: Load with specific parameters")
    logger.info("="*60)

    param_keys = {'max_opening', 'min_opening', 'interpolate_cross_section_count'}

    try:
        topology = HydroObjectUtilsV2.build_waterway_topology(
            modeling_yml_uri=modeling_url,
            param_keys=param_keys,
            with_metrics_code=True
        )

        logger.info(f"✓ Loaded topology with filtered parameters: {param_keys}")

        # Show object with children and metrics
        if topology.top_objects:
            obj = topology.top_objects[0]
            logger.info(f"\nExample object: {obj.object_name}")
            logger.info(f"  Type: {obj.object_type}")
            logger.info(f"  Parameters: {obj.params}")

            if obj.children:
                child = obj.children[0]
                logger.info(f"\n  First child: {child.object_name}")
                logger.info(f"    Type: {child.object_type}")
                logger.info(f"    Parameters: {child.params}")
                logger.info(f"    Metrics: {child.metrics}")

    except Exception as e:
        logger.error(f"✗ Failed to load topology: {e}")
        return

    print()

    # Example 3: Query topology
    logger.info("Example 3: Query topology")
    logger.info("="*60)

    if topology.top_objects:
        obj = topology.top_objects[0]
        obj_id = obj.object_id

        # Get object by ID
        retrieved = topology.get_object(obj_id)
        logger.info(f"✓ Retrieved object {obj_id}: {retrieved.object_name}")

        # Find neighbors
        neighbors = topology.find_neighbors(obj_id)
        logger.info(f"✓ Neighbors of {obj_id}:")
        logger.info(f"    Upstream: {neighbors['upstream']}")
        logger.info(f"    Downstream: {neighbors['downstream']}")

        # Get child's parent
        if obj.children:
            child_id = obj.children[0].object_id
            parent = topology.get_top_object_by_child_id(child_id)
            logger.info(f"✓ Parent of child {child_id}: {parent.object_name}")

    print()

    # Example 4: Filter objects
    logger.info("Example 4: Filter objects by type")
    logger.info("="*60)

    # Get all CrossSection children
    cross_sections = topology.get_objects(
        child_object_types={'CrossSection'}
    )
    logger.info(f"✓ Found {len(cross_sections)} objects (including CrossSection children)")

    # Count by type
    type_counts = {}
    for obj in cross_sections:
        obj_type = obj.object_type
        type_counts[obj_type] = type_counts.get(obj_type, 0) + 1

    logger.info("  Object type distribution:")
    for obj_type, count in sorted(type_counts.items()):
        logger.info(f"    - {obj_type}: {count}")


if __name__ == "__main__":
    main()
