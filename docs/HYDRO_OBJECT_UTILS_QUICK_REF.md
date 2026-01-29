# Quick Reference: HydroObjectUtilsV2

## Import

```python
from hydros_agent_sdk.utils import HydroObjectUtilsV2
```

## Load Topology

### Simple (with defaults)
```python
topology = HydroObjectUtilsV2.from_url("http://example.com/objects.yaml")
```

### With Options
```python
topology = HydroObjectUtilsV2.build_waterway_topology(
    modeling_yml_uri="http://example.com/objects.yaml",
    param_keys={'max_opening', 'min_opening'},  # Optional: filter parameters
    with_metrics_code=True  # Optional: generate metrics codes
)
```

## Access Objects

### Iterate Top-Level Objects
```python
for obj in topology.top_objects:
    print(f"{obj.object_name} ({obj.object_type})")
    print(f"  Parameters: {obj.params}")
    print(f"  Children: {len(obj.children)}")
```

### Iterate Children
```python
for obj in topology.top_objects:
    for child in obj.children:
        print(f"{child.object_name} ({child.object_type})")
        print(f"  Metrics: {child.metrics}")
```

## Query Topology

### Get Object by ID
```python
obj = topology.get_object(1018)  # Returns TopHydroObject or SimpleChildObject
```

### Get Top-Level Object by ID
```python
top_obj = topology.get_top_object(1018)  # Returns TopHydroObject only
```

### Get Parent of Child
```python
parent = topology.get_top_object_by_child_id(1052)
```

### Check if Object is Child
```python
is_child = topology.is_child_object(1052)  # Returns bool
```

### Find Neighbors
```python
neighbors = topology.find_neighbors(1018)
print(f"Upstream: {neighbors['upstream']}")
print(f"Downstream: {neighbors['downstream']}")
```

## Filter Objects

### By Managed IDs
```python
managed_ids = {1018, 1019, 1020}
objects = topology.get_objects(agent_managed_top_object_ids=managed_ids)
```

### By Child Types
```python
objects = topology.get_objects(child_object_types={'CrossSection', 'Gate'})
```

### By Both
```python
objects = topology.get_objects(
    agent_managed_top_object_ids={1018, 1019},
    child_object_types={'CrossSection'}
)
```

## Use in Agent

```python
from hydros_agent_sdk.agent_config import AgentConfigLoader
from hydros_agent_sdk.utils import HydroObjectUtilsV2

# In agent initialization
config = AgentConfigLoader.from_url(config_url)
modeling_url = config.get_property('hydros_objects_modeling_url')

topology = HydroObjectUtilsV2.build_waterway_topology(
    modeling_yml_uri=modeling_url,
    param_keys={'max_opening', 'min_opening'},
    with_metrics_code=True
)

# Use in agent logic
for obj in topology.top_objects:
    max_opening = obj.params.get('max_opening')
    # ... your logic here
```

## Data Models

### WaterwayTopology
- `top_objects: List[TopHydroObject]`
- `child_to_parent_map: Dict[int, int]`
- `upstream_map: Dict[int, List[int]]`
- `downstream_map: Dict[int, List[int]]`

### TopHydroObject
- `object_id: int`
- `object_type: str`
- `object_name: str`
- `params: Dict[str, Any]`
- `children: List[SimpleChildObject]`
- `km_pos: Optional[float]`

### SimpleChildObject
- `object_id: int`
- `object_type: str`
- `object_name: str`
- `params: Dict[str, Any]`
- `metrics: List[str]`

## Enums

### HydroObjectType
- `GATE_STATION`, `DIVERSION_POINT`, `CROSS_SECTION`
- `PUMP_STATION`, `GATE`, `SENSOR`
- `CHANNEL`, `SIPHON`, `TURBINE`

### MetricsCodes
- `WATER_LEVEL`, `WATER_FLOW`, `WATER_DEPTH`
- `GATE_OPENING`, `GATE_OPENING_PERCENTAGE`

## Error Handling

```python
try:
    topology = HydroObjectUtilsV2.from_url(modeling_url)
except Exception as e:
    logger.error(f"Failed to load topology: {e}")
    # Handle error
```

## Documentation

- Full docs: `docs/HYDRO_OBJECT_UTILS.md`
- Examples: `examples/hydro_object_utils_example.py`
- Tests: `tests/test_hydro_object_utils.py`
