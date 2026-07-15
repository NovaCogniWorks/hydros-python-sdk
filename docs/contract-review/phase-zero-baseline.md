# Phase 0 Java → Python AI contract review

Snapshot-SHA256: `baa057cad13578ceac3f9cdf3dccbd081734f2760417712f07ca6fd752563ce8`

The reviewer inspected the source-derived snapshot emitted by
`scripts/contract_sync_snapshot.py` against the current Java protocol source.
Java remains canonical. This record is invalid as soon as the snapshot hash
changes; regenerate the snapshot and review it again rather than editing a
verdict in isolation.

| Surface | Verdict | Evidence |
| --- | --- | --- |
| SimTaskInitRequest | PASS | Java and Python use the same selected wire fields and snake-case names. |
| TickCmdResponse | PASS | `completed_step` is required on both sides. |
| MpcExecutionStatusReport | PASS | Field names and current execution-status enum values match. |
| EdgeControlExecutionReport | PASS | Java and Python use `exec_run_id`; obsolete `control_run_id` is not remapped. |
| HydroCmd | PASS | A single Python command root has required `command_id`, matching Java. |
| AgentCommand | PASS | Direct fields, wire names, optionality and OffsetDateTime JSON handling match. |
| AgentCommandRequest | PASS | `need_ack_reply` and `acked` match Java nullable fields. |
| AgentCommandResponse | PASS | Success and error fields match Java response fields. |
| HydroCommandReceivedAckReply | PASS | The annotated subtype value matches; payload fields are inherited from AgentCommand. |
| HydroEventReportRequest | REVIEW | Nullable `risk_alert` matches the outer field, but Java HydroRiskAlert has no typed Python nested mirror yet. |
| HydroEventReportResponse | PASS | The annotated subtype value matches; payload fields are inherited from AgentCommandResponse. |
| HydroStationTargetValueRequest | PASS | Python now includes target-value map and control-group fields present in Java. |
| HydroStationTargetValueResponse | PASS | Python now includes object id and target-value map present in Java. |
| AgentCommandCatalog | PASS | The five supported AGTCMD constants and values match Java CommandTypes. |
| DeviceValueTypeEnum | PASS | Names, codes, labels and scalar value categories match the Java enum, including the shared `WATER_FLOW` member with `water_flow`, `水流量`, and corresponding Java `Float` / Python `float` scalar types. |
| Python protocol public API boundary | PASS | Only DTOs and catalog are public; registry, envelope, decoder and ACK factory are excluded. |
