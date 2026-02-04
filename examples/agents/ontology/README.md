# Ontology Simulation Agent Example

This directory contains a complete example of implementing an ontology-based simulation agent.

## File Structure

```
ontology/
├── README.md                    # This file
├── agent.properties             # Agent configuration (agent_code, agent_type, etc.)
├── ontology_agent.py           # Agent implementation class
└── ontology_rule_engine.py     # Example ontology rule engine implementation
```

## Learning Path

### 1. Start with `ontology_agent.py` - Agent Implementation

This file shows you **what interfaces you need to implement**:

- `MyOntologySimulationAgent` - Concrete agent class
- `_initialize_ontology_model()` - Initialize your ontology model
- `_execute_ontology_simulation()` - Execute reasoning for each step
- `_collect_boundary_conditions()` - Gather input data
- `_convert_results_to_metrics()` - Format output data

**Key takeaway**: Focus on the agent lifecycle and SDK integration, not the reasoning details.

### 2. Then look at `ontology_rule_engine.py` - Example Implementation

This file shows you **how to implement the reasoning logic**:

- `OntologyRuleEngine` - Example rule engine class
- `load_ontology()` - Build ontology model from topology
- `_load_rules()` - Define ontology rules and constraints
- `apply_rules()` - Execute rule-based reasoning

**Key takeaway**: This is just a demonstration. Replace it with your real ontology reasoner (OWL API, RDFLib, etc.).

### 3. Run the Example

```bash
# Run standalone
python ontology_agent.py

# Or run with multi-agent launcher
cd ../..
python multi_agent_launcher.py ontology
```

## Customization Guide

### Replace the Example Rule Engine

1. Keep `ontology_agent.py` structure (agent lifecycle management)
2. Replace `ontology_rule_engine.py` with your real reasoner
3. Update the import in `ontology_agent.py` if you rename the file
4. Implement the same interface: `load_ontology()` and `apply_rules()`

### Example: Using RDFLib

```python
# Create rdf_reasoner.py
from rdflib import Graph, Namespace

class RdfReasoner:
    def __init__(self):
        self.graph = Graph()
        self.ns = Namespace("http://example.org/water#")

    def load_ontology(self, topology):
        # Load ontology from file
        self.graph.parse("water_network.owl")

        # Add topology instances
        for top_obj in topology.top_objects:
            for child in top_obj.children:
                # Create RDF triples
                self.graph.add((
                    self.ns[child.object_name],
                    self.ns.hasType,
                    self.ns[child.object_type]
                ))

    def apply_rules(self, step, boundary_conditions):
        # Execute SPARQL queries
        query = """
            SELECT ?object ?waterLevel ?flow
            WHERE {
                ?object ns:hasWaterLevel ?waterLevel .
                ?object ns:hasFlow ?flow .
            }
        """
        results = self.graph.query(query)
        # ... process results ...
        return results
```

Then update `ontology_agent.py`:
```python
from rdf_reasoner import RdfReasoner  # Changed import

class MyOntologySimulationAgent(OntologySimulationAgent):
    def _initialize_ontology_model(self):
        self._rule_engine = RdfReasoner()  # Use real reasoner
        # ... rest stays the same ...
```

## Key Concepts

- **Ontology**: Formal representation of water network knowledge (concepts, relationships, constraints)
- **Rule Engine**: Applies logical rules to infer new facts from existing knowledge
- **Reasoning**: Process of deriving conclusions from ontology and rules
- **Constraints**: Logical rules that must be satisfied (e.g., water level bounds, flow conservation)

## Ontology vs Digital Twins

| Aspect | Ontology Agent | Digital Twins Agent |
|--------|---------------|---------------------|
| **Approach** | Rule-based reasoning | Physics-based simulation |
| **Complexity** | Lower computational cost | Higher computational cost |
| **Accuracy** | Approximate, constraint-based | High-fidelity, equation-based |
| **Use Case** | Quick analysis, constraint checking | Detailed prediction, what-if scenarios |
| **Example** | "If gate opening > 0.8, then flow is high" | Solve Saint-Venant equations |

## Example Rules

The example implementation includes these simple rules:

1. **Water Level Constraint**: `water_level <= 10.0`
2. **Flow Constraint**: `flow >= 0.0`
3. **Gate Opening Constraint**: `gate_opening <= 1.0`

In a real implementation, you would have more sophisticated rules:

```python
# Example: Conservation of mass
{
    'name': 'mass_conservation',
    'condition': lambda obj: obj['type'] == 'Junction',
    'action': lambda obj: obj['state'].update({
        'outflow': sum(obj['inflows']) - obj['storage_change']
    })
}

# Example: Gate control logic
{
    'name': 'gate_control',
    'condition': lambda obj: obj['state']['water_level'] > obj['threshold'],
    'action': lambda obj: obj['state'].update({'gate_opening': 1.0})
}
```

## Next Steps

1. Understand the agent lifecycle by reading `ontology_agent.py`
2. Study the example rule engine in `ontology_rule_engine.py`
3. Run the example to see it in action
4. Replace the example engine with your real ontology reasoner
5. Define your domain-specific rules and constraints
6. Test with real topology and boundary conditions
