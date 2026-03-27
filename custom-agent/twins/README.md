# Digital Twins Simulation Agent Example

This directory contains a complete example of implementing a digital twins simulation agent.

## File Structure

```
twins/
├── README.md                 # This file
├── agent.properties          # Agent configuration (agent_code, agent_type, etc.)
├── twins_agent.py           # Agent implementation class
└── hydraulic_solver.py      # Example hydraulic solver implementation
```

## Learning Path

### 1. Start with `twins_agent.py` - Agent Implementation

This file shows you **what interfaces you need to implement**:

- `MyTwinsSimulationAgent` - Concrete agent class
- `_initialize_twins_model()` - Initialize your simulation model
- `_execute_twins_simulation()` - Execute simulation for each step
- `on_boundary_condition_update()` - Handle external data updates

**Key takeaway**: Focus on the agent lifecycle and SDK integration, not the simulation details.

### 2. Then look at `hydraulic_solver.py` - Example Implementation

This file shows you **how to implement the simulation logic**:

- `HydraulicSolver` - Example solver class
- `initialize()` - Set up solver state from topology
- `solve_step()` - Compute hydraulic equations for one time step

**Key takeaway**: This is just a demonstration. Replace it with your real solver (SWMM, HEC-RAS, etc.).

### 3. Run the Example

```bash
# Run standalone
python twins_agent.py

# Or run with multi-agent launcher
cd ../..
python multi_agent_launcher.py twins
```

## Customization Guide

### Replace the Example Solver

1. Keep `twins_agent.py` structure (agent lifecycle management)
2. Replace `hydraulic_solver.py` with your real solver
3. Update the import in `twins_agent.py` if you rename the file
4. Implement the same interface: `initialize()` and `solve_step()`

### Example: Using SWMM

```python
# Create swmm_solver.py
from pyswmm import Simulation

class SwmmSolver:
    def __init__(self):
        self.sim = None

    def initialize(self, topology):
        # Initialize SWMM simulation
        self.sim = Simulation('model.inp')
        self.sim.start()

    def solve_step(self, step, boundary_conditions):
        # Run SWMM for one time step
        self.sim.step_advance(step)
        # ... extract results ...
        return results
```

Then update `twins_agent.py`:
```python
from swmm_solver import SwmmSolver  # Changed import

class MyTwinsSimulationAgent(TwinsSimulationAgent):
    def _initialize_twins_model(self):
        self._hydraulic_solver = SwmmSolver()  # Use real solver
        # ... rest stays the same ...
```

## Key Concepts

- **Digital Twins**: High-fidelity simulation synchronized with real-world systems
- **Hydraulic Solver**: Computes water network state (water level, flow, pressure, etc.)
- **Boundary Conditions**: External inputs (rainfall, gate operations, sensor data, etc.)
- **Time Series**: Historical and real-time data used to drive simulation

## Next Steps

1. Understand the agent lifecycle by reading `twins_agent.py`
2. Study the example solver in `hydraulic_solver.py`
3. Run the example to see it in action
4. Replace the example solver with your real implementation
5. Test with real topology and boundary conditions
