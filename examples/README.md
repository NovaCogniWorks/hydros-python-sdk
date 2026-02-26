# Hydros Agent SDK - Examples

This directory contains example implementations and business logic for Hydros simulation agents.

## 📁 Directory Structure

```
examples/
├── env.properties                 # Environment configuration (MQTT, cluster info)
├── simple_multi_agent_example.py  # Simple multi-agent example
├── multi_agent_launcher.py        # Command-line launcher for multiple agents
├── start_agents.sh                # Shell script to start agents
│
└── agents/                        # Agent implementations
    ├── ontology/                  # Ontology-based simulation agent
    │   ├── agent.properties       # Agent metadata configuration
    │   ├── ontology_agent.py      # Agent implementation example
    │   └── ontology_rule_engine.py  # Business logic: rule engine
    │
    ├── twins/                     # Digital twins simulation agent
    │   ├── agent.properties       # Agent metadata configuration
    │   ├── twins_agent.py         # Agent implementation example
    │   └── hydraulic_solver.py    # Business logic: hydraulic solver
    │
    └── centralscheduling/         # Central scheduling agent (placeholder)
        └── agent.properties
```

## 🎯 What's in Examples vs SDK

### SDK (hydros_agent_sdk/) - Framework Code

**Do NOT modify these - they are part of the pip package:**

- `HydroAgentFactory` - Factory for creating agent instances
- `MultiAgentCallback` - Multi-agent coordination callback
- `load_env_config()` - Environment configuration loader
- `BaseHydroAgent` - Base agent class
- `SimCoordinationClient` - MQTT coordination client
- Specialized agent base classes (TwinsSimulationAgent, OntologySimulationAgent, etc.)

### Examples (examples/) - Business Logic & Samples

**You CAN and SHOULD modify these:**

- **Business Logic Modules** (your custom implementations):
  - `ontology_rule_engine.py` - Ontology reasoning rules
  - `hydraulic_solver.py` - Hydraulic calculation logic
  - Add your own: `my_solver.py`, `my_optimizer.py`, etc.

- **Agent Implementations** (examples showing how to use SDK):
  - `ontology_agent.py` - How to implement ontology agent
  - `twins_agent.py` - How to implement twins agent
  - Add your own agent implementations here

- **Configuration Files**:
  - `env.properties` - MQTT broker and cluster configuration
  - `agent.properties` - Agent metadata (code, type, name)

- **Utility Scripts**:
  - `multi_agent_launcher.py` - Launch multiple agents
  - `simple_multi_agent_example.py` - Simple usage example

## 🚀 Quick Start

### 1. Configure Environment

Edit `env.properties`:

```properties
mqtt_broker_url=tcp://192.168.1.24
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/default_cluster
hydros_cluster_id=default_cluster
hydros_node_id=default_central
```

### 2. Run a Single Agent

```bash
# Run ontology agent
cd examples/agents/ontology
python ontology_agent.py

# Run twins agent
cd examples/agents/twins
python twins_agent.py
```

### 3. Run Multiple Agents

```bash
# Run multiple agents in one process
cd examples
python multi_agent_launcher.py twins ontology

# Or use the simple example
python simple_multi_agent_example.py
```

### 4. Use the Launcher Tool

```bash
cd examples

# Launch specific agents
python multi_agent_launcher.py twins ontology

# Launch all agents
python multi_agent_launcher.py --all

# Enable debug mode
python multi_agent_launcher.py --debug twins

# Show help
python multi_agent_launcher.py --help
```

## 💡 How to Create Your Own Agent

### Step 1: Choose a Base Class

```python
from hydros_agent_sdk import (
    TwinsSimulationAgent,      # For high-fidelity simulation
    OntologySimulationAgent,   # For ontology-based reasoning
    ModelCalculationAgent,     # For event-driven calculation
    CentralSchedulingAgent,    # For MPC optimization
)
```

### Step 2: Implement Your Agent

```python
from hydros_agent_sdk import (
    TwinsSimulationAgent,
    HydroAgentFactory,
    MultiAgentCallback,
    load_env_config,
)

class MyCustomAgent(TwinsSimulationAgent):
    """Your custom agent implementation."""

    def _initialize_twins_model(self):
        """Initialize your simulation model."""
        # Load your custom solver
        self.solver = MyCustomSolver()
        self.solver.initialize(self._topology)

    def _execute_twins_simulation(self, step: int):
        """Execute one simulation step."""
        # Collect boundary conditions
        bc = self._collect_boundary_conditions(step)
        
        # Run your solver
        results = self.solver.solve(step, bc)
        
        # Convert to metrics
        return self._convert_results_to_metrics(results)
```

### Step 3: Create Business Logic Module

Create `my_solver.py`:

```python
class MyCustomSolver:
    """Your custom solver implementation."""
    
    def initialize(self, topology):
        """Initialize solver with topology."""
        pass
    
    def solve(self, step, boundary_conditions):
        """Solve for one time step."""
        # Your calculation logic here
        return results
```

### Step 4: Configure Your Agent

Create `agent.properties`:

```properties
agent_code=MY_CUSTOM_AGENT
agent_type=TWINS_SIMULATION_AGENT
agent_name=My Custom Agent
```

### Step 5: Run Your Agent

```python
def main():
    # Load configuration
    env_config = load_env_config()
    
    # Create factory
    factory = HydroAgentFactory(
        agent_class=MyCustomAgent,
        config_file="./agent.properties",
        env_config=env_config
    )
    
    # Create callback and register factory
    callback = MultiAgentCallback()
    callback.register_agent_factory("MY_CUSTOM_AGENT", factory)
    
    # Create and start client
    client = SimCoordinationClient(
        broker_url=env_config['mqtt_broker_url'],
        broker_port=int(env_config['mqtt_broker_port']),
        topic=env_config['mqtt_topic'],
        sim_coordination_callback=callback
    )
    callback.set_client(client)
    client.start()
    
    # Keep running
    while True:
        time.sleep(1)
```

## 📚 Examples Explained

### 1. Ontology Simulation Agent

**Purpose**: Demonstrates ontology-based reasoning for water network simulation.

**Key Files**:
- `ontology_agent.py` - Agent implementation
- `ontology_rule_engine.py` - Business logic (rule-based reasoning)

**What it shows**:
- How to inherit from `OntologySimulationAgent`
- How to implement `_initialize_ontology_model()`
- How to implement `_execute_ontology_simulation()`
- How to integrate custom business logic (rule engine)

### 2. Digital Twins Simulation Agent

**Purpose**: Demonstrates high-fidelity hydraulic simulation.

**Key Files**:
- `twins_agent.py` - Agent implementation
- `hydraulic_solver.py` - Business logic (hydraulic calculations)

**What it shows**:
- How to inherit from `TwinsSimulationAgent`
- How to implement `_initialize_twins_model()`
- How to implement `_execute_twins_simulation()`
- How to handle boundary condition updates
- How to integrate custom business logic (solver)

### 3. Multi-Agent Example

**Purpose**: Shows how to run multiple agent types in one process.

**Key Files**:
- `simple_multi_agent_example.py` - Simple example
- `multi_agent_launcher.py` - Full-featured launcher

**What it shows**:
- How to use `MultiAgentCallback`
- How to register multiple agent factories
- How to handle multiple agent types
- Command-line argument parsing
- Debug mode support

## 🔧 Configuration Files

### env.properties (Environment Configuration)

Shared by all agents in this directory:

```properties
# MQTT Broker Configuration
mqtt_broker_url=tcp://192.168.1.24
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/default_cluster

# Cluster Configuration
hydros_cluster_id=default_cluster
hydros_node_id=default_central
```

### agent.properties (Agent Metadata)

Each agent has its own configuration:

```properties
# Agent Identification
agent_code=TWINS_SIMULATION_AGENT
agent_type=TWINS_SIMULATION_AGENT
agent_name=Twins Simulation Agent
```

## 🐛 Debugging

### Enable Debug Logging

```python
from hydros_agent_sdk import setup_logging
import logging

setup_logging(
    level=logging.DEBUG,  # Change to DEBUG
    console=True,
    log_file="hydros.log",
    use_rolling=True
)
```

### Use Remote Debugger

```bash
# Install debugpy
pip install debugpy

# Run with debug mode
python multi_agent_launcher.py --debug twins
```

Then attach your IDE debugger to `localhost:5678`.

See `DEBUG_GUIDE.md` for detailed debugging instructions.

## 📖 Additional Resources

- **SDK Documentation**: See `../CLAUDE.md` for SDK architecture
- **Refactoring Plan**: See `../REFACTORING_PLAN.md` for code organization
- **API Reference**: Check SDK source code for detailed API docs

## ❓ FAQ

### Q: Can I modify files in `hydros_agent_sdk/`?

**A**: No. The SDK is framework code and will be distributed as a pip package. Only modify files in `examples/`.

### Q: Where should I put my custom business logic?

**A**: Create new Python modules in `examples/agents/your_agent/` directory. For example:
- `my_solver.py` - Your custom solver
- `my_optimizer.py` - Your custom optimizer
- `my_rules.py` - Your custom rules

### Q: How do I add a new agent type?

**A**: 
1. Create a new directory: `examples/agents/my_agent/`
2. Create `agent.properties` with your agent metadata
3. Create `my_agent.py` inheriting from appropriate base class
4. Create your business logic modules
5. Register in `multi_agent_launcher.py` if needed

### Q: Can I use a different MQTT broker?

**A**: Yes, just update `env.properties` with your broker URL and port.

### Q: How do I run multiple agents on different machines?

**A**: Each machine should:
1. Have its own `agent.properties` with unique `agent_code`
2. Share the same `env.properties` (same MQTT broker)
3. Run its own agent process

## 🤝 Contributing

When adding new examples:

1. **Keep business logic separate** - Create dedicated modules for your logic
2. **Follow naming conventions** - Use descriptive names for files and classes
3. **Add documentation** - Include docstrings and comments
4. **Test thoroughly** - Ensure your example works end-to-end
5. **Update this README** - Add your example to the list

---

**Last Updated**: 2026-02-04
**SDK Version**: 0.1.3
