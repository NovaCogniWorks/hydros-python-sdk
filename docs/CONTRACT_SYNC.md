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
- Agent-command baseline: `HydroCmd`, the agent-command base hierarchy, ACK,
  event report request/response, station target-value request/response,
  `AgentCommandCatalog`, and `DeviceValueTypeEnum`.

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

For the agent-command section, compare only the DTO subset explicitly listed in
the snapshot. `AgentCommandDecoder` and `AgentCommandAckFactory` are Python
runtime components and must be excluded from DTO field comparison. The Python
protocol export list is evidence too: registry APIs and artificial envelopes
must not reappear as public wire-contract types.

## Phase 2 AI review gate

The SDK does not introduce JSON Schema or DTO generation. Instead, a tracked
AI review record binds the reviewer decision to the exact source-derived
snapshot using SHA-256. The gate regenerates the snapshot and fails if the
record is stale, omits a selected surface, contains `FAIL`, or adds an
unapproved `REVIEW`.

```bash
python scripts/contract_ai_review_gate.py \
  --java-protocol-root ../../hydros-agent-parent/hydros-agent-protocol
```

The reviewer writes [`docs/contract-review/phase-zero-baseline.md`](contract-review/phase-zero-baseline.md)
after inspecting the generated input. The only temporarily allowed `REVIEW` is
`HydroEventReportRequest`: Java's nested `HydroRiskAlert` does not yet have a
typed Python mirror. Every other selected surface must be `PASS`; a new review
record is required whenever the source snapshot changes.

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
| Agent-command DTO subset | REVIEW | Python now mirrors Java's current station target-value fields, uses a single `HydroCmd` root, mirrors the five supported `AGTCMD_*` constants and `DeviceValueTypeEnum`, and keeps decoder / ACK construction out of the protocol public API. `HydroEventReportRequest.risk_alert` remains an untyped JSON-object mirror of Java `HydroRiskAlert`; its nested object shape needs a dedicated future surface before Python introduces a typed model. |

## Required verification

Run all three after a Phase 0 change:

```bash
python scripts/contract_sync_snapshot.py \
  --java-protocol-root ../../hydros-agent-parent/hydros-agent-protocol

python -m pytest -q \
  tests/test_contract_sync_snapshot.py \
  tests/test_protocol_agent_commands.py \
  tests/test_protocol_agent_instance_compat.py

mvn -q -Dtest=CommandSubtypeRegistrationTest test
```

The Maven command runs from `hydros-agent-parent/hydros-agent-protocol`.
