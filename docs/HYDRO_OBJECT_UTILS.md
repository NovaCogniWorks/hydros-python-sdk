# HydroObjectUtilsV2 - Water Network Topology Utility

## Overview

The `HydroObjectUtilsV2` utility class provides functionality for loading and parsing complex water network topology objects from YAML configuration files. This is the Python equivalent of the Java `com.hydros.agent.common.utils.HydroObjectUtilsV2` class.

## Features

- **Load topology from remote YAML files** - Fetch and parse water network configurations from URLs
- **Parameter filtering** - Select specific parameters to load (e.g., only `max_opening`, `min_opening`)
- **Metrics code generation** - Automatically generate metrics codes for child objects (water level, flow, gate opening)
- **Topology indices** - Build optimized indices for child-to-parent, upstream, and downstream relationships
- **Object caching** - Fast O(1) lookups for objects by ID
- **Flexible querying** - Filter objects by type, managed IDs, and relationships

## Quick Start

### Basic Usage

```python
from hydros_agent_sdk.utils import HydroObjectUtilsV2

# Load topology with default settings
topology = HydroObjectUtilsV2.from_url(
    "http://example.com/objects.yaml"
)

print(f"Loaded {len(topology.top_objects)} objects")
```

### Load with Specific Parameters

```python
# Only load specific parameters
param_keys = {'max_opening', 'min_opening', 'interpolate_cross_section_count'}

topology = HydroObjectUtilsV2.build_waterway_topology(
    modeling_yml_uri="http://example.com/objects.yaml",
    param_keys=param_keys,
    with_metrics_code=True
)
```

### Use in Agent Initialization

```python
from hydros_agent_sdk.agent_config import AgentConfigLoader
from hydros_agent_sdk.utils import HydroObjectUtilsV2

# Load agent configuration
agent_config = AgentConfigLoader.from_url(config_url)

# Get modeling URL from configuration
modeling_url = agent_config.get_property('hydros_objects_modeling_url')

# Load water network topology
topology = HydroObjectUtilsV2.build_waterway_topology(
    modeling_yml_uri=modeling_url,
    param_keys={'max_opening', 'min_opening'},
    with_metrics_code=True
)

# Access topology in your agent
for obj in topology.top_objects:
    print(f"Object: {obj.object_name} ({obj.object_type})")
    print(f"  Children: {len(obj.children)}")
```

## Data Models

### WaterwayTopology

The main container for the complete water network topology.

**Properties:**
- `top_objects: List[TopHydroObject]` - List of top-level hydro objects
- `child_to_parent_map: Dict[int, int]` - Maps child IDs to parent IDs
- `upstream_map: Dict[int, List[int]]` - Maps objects to upstream neighbors
- `downstream_map: Dict[int, List[int]]` - Maps objects to downstream neighbors

**Methods:**
- `get_top_object(top_object_id)` - Get top-level object by ID
- `get_object(object_id)` - Get any object (parent or child) with caching
- `get_top_object_by_child_id(child_id)` - Find parent of a child object
- `is_child_object(object_id)` - Check if ID is a child object
- `get_objects(managed_ids, child_types)` - Filter objects by criteria
- `find_neighbors(object_id)` - Get upstream/downstream neighbors

### TopHydroObject

Represents a top-level hydro object (e.g., GateStation, Channel).

**Properties:**
- `object_id: int` - Unique identifier
- `object_type: str` - Type code (e.g., "GateStation", "Channel")
- `object_name: str` - Display name
- `params: Dict[str, Any]` - Custom parameters
- `children: List[SimpleChildObject]` - Child objects
- `km_pos: Optional[float]` - Kilometer position in waterway

### SimpleChildObject

Represents child objects (cross-sections, gates, sensors).

**Properties:**
- `object_id: int` - Unique identifier
- `object_type: str` - Type code
- `object_name: str` - Display name
- `params: Dict[str, Any]` - Custom parameters
- `metrics: List[str]` - Associated metrics codes

## Enumerations

### HydroObjectType

```python
class HydroObjectType(str, Enum):
    GATE_STATION = "GateStation"
    DIVERSION_POINT = "DiversionPoint"
    CROSS_SECTION = "CrossSection"
    PUMP_STATION = "PumpStation"
    GATE = "Gate"
    SENSOR = "Sensor"
    CHANNEL = "Channel"
    SIPHON = "Siphon"
    TURBINE = "Turbine"
```

### MetricsCodes

```python
class MetricsCodes(str, Enum):
    WATER_LEVEL = "water_level"
    WATER_FLOW = "water_flow"
    GATE_OPENING = "gate_opening"
    GATE_OPENING_PERCENTAGE = "gate_opening_percentage"
    WATER_DEPTH = "water_depth"
```

## Usage Examples

### Example 1: Iterate Through Objects

```python
topology = HydroObjectUtilsV2.from_url(modeling_url)

for top_obj in topology.top_objects:
    print(f"Object: {top_obj.object_name} ({top_obj.object_type})")
    print(f"  Parameters: {top_obj.params}")

    for child in top_obj.children:
        print(f"  Child: {child.object_name} ({child.object_type})")
        print(f"    Metrics: {child.metrics}")
```

### Example 2: Query Topology Relationships

```python
# Get object by ID
obj = topology.get_object(1018)
print(f"Found: {obj.object_name}")

# Find neighbors
neighbors = topology.find_neighbors(1018)
print(f"Upstream: {neighbors['upstream']}")
print(f"Downstream: {neighbors['downstream']}")

# Get parent of child object
parent = topology.get_top_object_by_child_id(1052)
print(f"Parent: {parent.object_name}")
```

### Example 3: Filter Objects

```python
# Get all objects with CrossSection children
objects = topology.get_objects(
    child_object_types={'CrossSection', 'Gate'}
)

# Filter by managed object IDs
managed_ids = {1018, 1019, 1020}
objects = topology.get_objects(
    agent_managed_top_object_ids=managed_ids
)
```

### Example 4: Access Parameters and Metrics

```python
topology = HydroObjectUtilsV2.build_waterway_topology(
    modeling_yml_uri=modeling_url,
    param_keys={'max_opening', 'min_opening'},
    with_metrics_code=True
)

for obj in topology.top_objects:
    # Access parameters
    max_opening = obj.params.get('max_opening')
    if max_opening:
        print(f"{obj.object_name}: max_opening = {max_opening}")

    # Access child metrics
    for child in obj.children:
        if MetricsCodes.WATER_LEVEL in child.metrics:
            print(f"  {child.object_name} has water level sensor")
```

## YAML File Structure

The utility expects YAML files with this structure:

```yaml
objects:
  - id: 1018
    name: "Gate Station A"
    type: "GateStation"
    parameters:
      max_opening: 5.0
      min_opening: 0.0
    cross_section_children:
      - id: 1052
        name: "Cross Section 1"
        type: "CrossSection"
    device_children:
      - id: 2001
        name: "Gate 1"
        type: "Gate"
        parameters:
          max_opening: 5.0

cross_sections:
  - id: 1052
    name: "Cross Section 1"
    type: "CrossSection"
    parameters:
      interpolate_cross_section_count: 5
      boundary_type: 0

connections:
  - from:
      id: 1018
    to:
      id: 1019
```

## API Reference

### HydroObjectUtilsV2.build_waterway_topology()

```python
@staticmethod
def build_waterway_topology(
    modeling_yml_uri: str,
    param_keys: Optional[Set[str]] = None,
    with_metrics_code: bool = False
) -> WaterwayTopology
```

**Parameters:**
- `modeling_yml_uri` - URL of the YAML configuration file
- `param_keys` - Set of parameter keys to include (None = include all)
- `with_metrics_code` - Whether to generate metrics codes for child objects

**Returns:**
- `WaterwayTopology` object containing the complete topology

### HydroObjectUtilsV2.from_url()

```python
@classmethod
def from_url(cls, url: str) -> WaterwayTopology
```

Convenience method to load topology with default settings (includes metrics codes).

**Parameters:**
- `url` - URL of the YAML configuration file

**Returns:**
- `WaterwayTopology` object

### HydroObjectUtilsV2.load_remote_yaml()

```python
@staticmethod
def load_remote_yaml(url: str) -> Dict[str, Any]
```

Load YAML content from a remote URL.

**Parameters:**
- `url` - The URL of the YAML file

**Returns:**
- Parsed YAML content as a dictionary

## Testing

Run the test suite:

```bash
# Run all tests
pytest tests/test_hydro_object_utils.py

# Run with verbose output
pytest tests/test_hydro_object_utils.py -v

# Run standalone
python tests/test_hydro_object_utils.py
```

See `examples/hydro_object_utils_example.py` for more usage examples.

## Comparison with Java Implementation

This Python implementation mirrors the Java `HydroObjectUtilsV2` class with the following equivalents:

| Java | Python |
|------|--------|
| `HydroObjectUtilsV2.buildWaterwayTopology()` | `HydroObjectUtilsV2.build_waterway_topology()` |
| `WaterwayTopology` | `WaterwayTopology` |
| `TopHydroObject` | `TopHydroObject` |
| `SimpleChildObject` | `SimpleChildObject` |
| `HydroObjectType` enum | `HydroObjectType` enum |
| `MetricsCodes` enum | `MetricsCodes` enum |

## Error Handling

The utility raises exceptions for common error cases:

```python
try:
    topology = HydroObjectUtilsV2.from_url(modeling_url)
except Exception as e:
    logger.error(f"Failed to load topology: {e}")
    # Handle error appropriately
```

Common errors:
- **URL not accessible** - Network issues or invalid URL
- **Invalid YAML format** - Malformed YAML file
- **Missing required fields** - YAML missing `objects` or other required sections

## Performance Considerations

- **Object caching** - First lookup builds cache, subsequent lookups are O(1)
- **Parameter filtering** - Only requested parameters are loaded, reducing memory usage
- **Lazy loading** - Topology indices built once during initialization
- **URL encoding** - Handles non-ASCII characters (e.g., Chinese) in URLs automatically

## Thread Safety

The `WaterwayTopology` object is read-only after construction and safe for concurrent access. If you need to modify the topology, create a new instance.
