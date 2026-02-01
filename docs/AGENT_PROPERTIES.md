# Agent Properties and Configuration Loading

## Overview

This document describes the changes made to support dynamic agent configuration loading from `SimTaskInitRequest`, matching the Java implementation in `com.hydros.agent.configuration.AgentConfiguration`.

## Key Changes

### 1. New `AgentProperties` Class

Created `hydros_agent_sdk/agent_properties.py` that matches the Java implementation:

```python
class AgentProperties(dict):
    """
    Agent properties dictionary with typed accessor methods.

    Matches Java: com.hydros.agent.configuration.base.AgentProperties
    """

    def get_property_as_integer(self, property_name: str) -> int
    def get_property_as_string(self, property_name: str) -> str
    def get_property_as_float(self, property_name: str) -> float
    def get_property_as_bool(self, property_name: str) -> bool
    def get_property(self, property_name: str, default: Any = None) -> Any
```

This class extends `dict` to allow flexible key-value storage while providing typed accessor methods for safe property retrieval.

### 2. Updated `BaseHydroAgent`

**Added `properties` attribute:**
- Type: `AgentProperties` (dictionary with typed accessors)
- Initialized as empty dictionary in constructor
- Populated during `load_agent_configuration()` call

**Modified constructor:**
- `agent_configuration_url` is now **optional** (will be loaded from `SimTaskInitRequest`)
- Added `properties: AgentProperties` as instance attribute

**New method: `load_agent_configuration(request: SimTaskInitRequest)`**

This method implements the configuration loading logic:

1. **Extract `agent_configuration_url`** from `request.agent_list`:
   - Finds the `HydroAgent` in `agent_list` where `agent_code` matches
   - Gets the `agent_configuration_url` from that agent

2. **Load YAML configuration** via HTTP:
   - Uses `AgentConfigLoader.from_url()` to fetch and parse YAML

3. **Validate `agent_code`**:
   - Checks that `agent_code` in YAML matches the agent being instantiated
   - Raises `ValueError` if mismatch detected

4. **Set properties**:
   - Converts Pydantic model properties to dict
   - Updates `self.properties` with all key-value pairs from YAML

### 3. Updated `agent.properties` File

**Removed:**
- `agent_configuration_url` property (now loaded dynamically)

**Added comment:**
```properties
# Note: agent_configuration_url is now loaded dynamically from SimTaskInitRequest.agent_list
# and should not be specified in this file
```

### 4. Updated Example Code

Modified `examples/agent_example.py`:

**In `MySampleHydroAgent.__init__()`:**
- Removed `agent_configuration_url` from config loading
- Removed `agent_configuration_url` from parent constructor call

**In `MySampleHydroAgent.on_init()`:**
- Added call to `self.load_agent_configuration(request)` at the beginning
- This loads configuration from `SimTaskInitRequest` before any other initialization
- Access properties using `self.properties.get_property()`

**Example usage:**
```python
def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
    # Load agent configuration from SimTaskInitRequest
    self.load_agent_configuration(request)

    # Access properties using typed accessors
    modeling_url = self.properties.get_property('hydros_objects_modeling_url')
    step_resolution = self.properties.get_property_as_integer('step_resolution')

    # Properties are now available for use
    ...
```

## Configuration Flow

### Before (Old Flow)

1. Agent reads `agent_configuration_url` from `agent.properties` file
2. Agent loads YAML configuration from URL in `on_init()`
3. No validation of `agent_code` match

### After (New Flow)

1. Agent reads basic config from `agent.properties` (no URL)
2. On `SimTaskInitRequest`:
   - Extract `agent_configuration_url` from `request.agent_list` by matching `agent_code`
   - Load YAML configuration via HTTP
   - Validate `agent_code` in YAML matches agent being instantiated
   - Set `self.properties` from YAML properties
3. Agent can access properties using typed accessors

## Benefits

1. **Dynamic Configuration**: Configuration URL comes from coordinator, not hardcoded
2. **Validation**: Ensures correct configuration file is loaded for each agent
3. **Type Safety**: Typed accessor methods prevent type errors
4. **Flexibility**: Different agent instances can have different properties
5. **Java Compatibility**: Matches Java implementation structure

## Usage Example

```python
class MyAgent(BaseHydroAgent):
    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        # Load configuration from SimTaskInitRequest
        self.load_agent_configuration(request)

        # Access properties with type safety
        step_resolution = self.properties.get_property_as_integer('step_resolution')
        modeling_url = self.properties.get_property_as_string('hydros_objects_modeling_url')
        enabled = self.properties.get_property_as_bool('driven_by_coordinator')

        # Use properties in initialization
        logger.info(f"Step resolution: {step_resolution}")

        # Continue with agent initialization
        ...
```

## Testing

Created `tests/test_agent_properties.py` with comprehensive tests for:
- Property creation and basic operations
- Typed accessor methods (integer, string, float, bool)
- Error handling for missing/invalid properties
- Default value handling

## Migration Guide

For existing agents:

1. **Remove `agent_configuration_url`** from `agent.properties` file
2. **Update agent constructor** to not pass `agent_configuration_url` to parent
3. **Add configuration loading** in `on_init()`:
   ```python
   def on_init(self, request: SimTaskInitRequest):
       self.load_agent_configuration(request)
       # ... rest of initialization
   ```
4. **Access properties** using `self.properties.get_property()` or typed accessors

## Notes

- The `agent_configuration_url` must be present in `SimTaskInitRequest.agent_list` for the agent
- If no URL is provided, a warning is logged and properties remain empty
- Properties are stored as a dictionary, allowing any key-value pairs from YAML
- Typed accessors provide safe type conversion with error handling
