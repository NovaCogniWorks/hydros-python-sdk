# Java → Python Contract Sync

## Canonical source

`hydros-agent-parent/hydros-agent-protocol` DTO source is the source of truth
for shared Hydros command, response, report, field, enum, and wire-name
semantics. Focused Java serialization tests are part of the review evidence.
The Python SDK mirrors that contract; it does not define a second contract.

The Phase 0 baseline deliberately does **not** use JSON Schema or DTO code
generation. Instead, it creates a small source-derived evidence bundle for an
AI reviewer to compare against the current Python Pydantic models.

## Produce AI review input

From the Python SDK repository:

```bash
python scripts/contract_sync_snapshot.py \
  --java-protocol-root ../../hydros-agent-parent/hydros-agent-protocol
```

The current baseline covers the contract surfaces already changed or consumed
by the SDK's main coordination path:

- `SimTaskInitRequest`
- `TickCmdResponse`
- `MpcExecutionStatusReport`
- `EdgeControlExecutionReport`

The command prints Java subtype annotations, direct Java field declarations and
their wire keys, plus Python field declarations. Give that output to an AI reviewer.
The reviewer must compare wire keys, requiredness, aliases, enum/value
semantics, and command subtype, then issue one result per surface:

```text
PASS    Java and Python mirror the same current contract.
REVIEW  The source does not establish the semantic relationship clearly.
FAIL    Python differs from current Java source or Java's focused contract test.
```

If Java DTO source and a Java focused serialization test disagree, report that
as a Java-internal `FAIL` first. Do not silently change Python to match a stale
test or introduce a second V2 wire field.

## Phase 0 baseline result

`EdgeControlExecutionReport` uses the Java source key `exec_run_id`. The Java
subtype registration test previously asserted the obsolete `control_run_id`;
that test is corrected in the same Phase 0 change. Python already emits and
accepts `exec_run_id`, so no Python alias is added. An unknown
`control_run_id` is ignored instead of being mapped to `exec_run_id`, matching
the Java parser's current behavior.

The current AI review baseline records the following outcome:

| Surface | Result | Evidence / decision |
| --- | --- | --- |
| `SimTaskInitRequest` | PASS | Java and Python use the same snake-case field set. Java `AgentProperties` is transported as a property map, which the Python mirror keeps as `Dict[str, Dict[str, Any]]`. |
| `TickCmdResponse` | PASS | `completed_step` is required on both sides. |
| `MpcExecutionStatusReport` | PASS | Field set and wire keys match. Python constrains `execution_status` to the current Java enum values. Timestamp values remain ISO-8601 wire strings in Python. |
| `EdgeControlExecutionReport` | PASS | Java source, Java subtype test, and Python all use `exec_run_id`; unknown `control_run_id` is ignored on both sides rather than mapped. Python-only `group_id`, `session_id`, and `sub_step_index` were removed. Python constrains `exec_status` to the Java enum values. |

## Required verification

Run all three after a Phase 0 change:

```bash
python scripts/contract_sync_snapshot.py \
  --java-protocol-root ../../hydros-agent-parent/hydros-agent-protocol

python -m pytest -q tests/test_protocol_agent_instance_compat.py

mvn -q -Dtest=CommandSubtypeRegistrationTest test
```

The Maven command runs from `hydros-agent-parent/hydros-agent-protocol`.
