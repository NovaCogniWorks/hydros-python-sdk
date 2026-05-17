import json
import unittest
from pathlib import Path

from hydros_agent_sdk.adapters.legacy import backfill_legacy_command_payload, normalize_command_payload
from hydros_agent_sdk.contract.v1 import (
    AgentDriveMode,
    AgentInstanceStatusReport as ContractAgentInstanceStatusReport,
    AgentInstanceStatus,
    AgentStatus,
    CommandStatus,
    HydroAlertUpdatedReport as ContractHydroAlertUpdatedReport,
    OutflowTimeSeriesRequest as ContractOutflowTimeSeriesRequest,
    ParameterIdentifiedReport as ContractParameterIdentifiedReport,
    SIMCMD_AGENT_INSTANCE_STATUS_REPORT,
    SIMCMD_HYDRO_ALERT_REPORT,
    SIMCMD_IDENTIFIED_PARAMS_REPORT,
    SIMCMD_OUTFLOW_TIME_SERIES_REQUEST,
    SIMCMD_TASK_INIT_REQUEST,
    SIMCMD_TASK_INIT_RESPONSE,
    SIMCMD_TASK_TERMINATE_REQUEST,
    SIMCMD_TASK_TERMINATE_RESPONSE,
    SIMCMD_TICK_CMD_REQUEST,
    SIMCMD_TICK_CMD_RESPONSE,
    SIMCMD_TIME_SERIES_CALCULATION_REQUEST,
    SIMCMD_TIME_SERIES_CALCULATION_RESPONSE,
    SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST,
    SimTaskInitRequest as ContractSimTaskInitRequest,
    SimTaskInitResponse as ContractSimTaskInitResponse,
    SimCommandEnvelope as ContractSimCommandEnvelope,
    TickCmdRequest as ContractTickCmdRequest,
    TickCmdResponse as ContractTickCmdResponse,
    TimeSeriesDataUpdateRequest as ContractTimeSeriesDataUpdateRequest,
)
from hydros_agent_sdk.protocol.commands import AgentInstanceStatusReport, SimCommandEnvelope
from hydros_agent_sdk.protocol.commands import SimTaskInitResponse as LegacySimTaskInitResponse


class CanonicalContractCompatibilityTest(unittest.TestCase):
    FIXTURE_DIR = (
        Path(__file__).resolve().parents[2]
        / "hydros-agent-parent"
        / "hydros-agent-protocol"
        / "src"
        / "main"
        / "resources"
        / "contract"
        / "v1"
        / "fixtures"
    )

    CONTRACT_DIR = FIXTURE_DIR.parent

    def test_normalize_legacy_task_init_payload_adds_contract_views(self):
        payload = {
            "command_id": "cmd-1",
            "command_type": "task_init_request",
            "broadcast": True,
            "context": {
                "biz_scene_instance_id": "bsi-1",
                "tenant": {"tenant_id": "tenant-1", "tenant_name": "Tenant"},
                "biz_scenario": {"biz_scenario_id": "scenario-1", "biz_scenario_name": "Scenario"},
                "waterway": {"waterway_id": "waterway-1", "waterway_name": "Waterway"},
                "valid": True,
            },
            "agent_list": [
                {
                    "agent_code": "CENTRAL_SCHEDULING_AGENT",
                    "agent_type": "CENTRAL_SCHEDULING",
                    "agent_name": "Central Scheduling Agent",
                    "agent_configuration_url": "central-config.json",
                    "drive_mode": "SIM_TICK_DRIVEN",
                }
            ],
        }

        normalized = normalize_command_payload(payload)
        command = ContractSimTaskInitRequest.model_validate(normalized)

        self.assertEqual("bsi-1", normalized["context_ref"]["biz_scene_instance_id"])
        self.assertEqual("tenant-1", normalized["context_ref"]["tenant_id"])
        self.assertEqual("CENTRAL_SCHEDULING_AGENT", normalized["agent_definition_refs"][0]["agent_code"])
        self.assertEqual("bsi-1", command.context_ref.biz_scene_instance_id)
        self.assertEqual("CENTRAL_SCHEDULING_AGENT", command.agent_definition_refs[0].agent_code)

    def test_legacy_status_report_parses_with_canonical_field_name(self):
        payload = {
            "command_id": "cmd-2",
            "command_type": "report_agent_instance_status",
            "broadcast": True,
            "context": {
                "biz_scene_instance_id": "bsi-1",
                "valid": True,
            },
            "source_agent_instance": {
                "agent_id": "agent-1",
                "agent_code": "CENTRAL_SCHEDULING_AGENT",
                "agent_type": "CENTRAL_SCHEDULING",
                "biz_scene_instance_id": "bsi-1",
                "hydros_cluster_id": "cluster-1",
                "hydros_node_id": "node-1",
                "context": {
                    "biz_scene_instance_id": "bsi-1",
                    "valid": True,
                },
                "agent_biz_status": "ACTIVE",
                "drive_mode": "SIM_TICK_DRIVEN",
            },
            "created_state": "WAITING",
        }

        normalized = normalize_command_payload(payload)
        legacy_envelope = SimCommandEnvelope(command=normalized)
        legacy_report = legacy_envelope.command
        contract_report = ContractAgentInstanceStatusReport.model_validate(normalized)

        self.assertIsInstance(legacy_report, AgentInstanceStatusReport)
        self.assertEqual("WAITING", legacy_report.agent_instance_status)
        self.assertEqual("WAITING", legacy_report.created_state)
        self.assertEqual("WAITING", normalized["agent_instance_status"])
        self.assertEqual("agent-1", normalized["source_agent_instance_ref"]["agent_id"])
        self.assertEqual("WAITING", contract_report.agent_instance_status.value)

    def test_contract_envelope_parses_normalized_payload(self):
        payload = {
            "command_id": "cmd-3",
            "command_type": "task_init_request",
            "broadcast": True,
            "context": {
                "biz_scene_instance_id": "bsi-2",
                "valid": True,
            },
            "agent_list": [
                {
                    "agent_code": "OUTFLOW_PLAN_AGENT",
                    "agent_type": "OUTFLOW_PLAN_AGENT",
                }
            ],
        }

        normalized = normalize_command_payload(payload)
        envelope = ContractSimCommandEnvelope(command=normalized)

        self.assertEqual("task_init_request", envelope.command.command_type)
        self.assertEqual("bsi-2", envelope.command.context_ref.biz_scene_instance_id)

    def test_first_batch_fixtures_parse_as_contract_models(self):
        fixture_models = {
            "task-init-request.json": ContractSimTaskInitRequest,
            "task-init-response.json": ContractSimTaskInitResponse,
            "tick-cmd-request.json": ContractTickCmdRequest,
            "tick-cmd-response.json": ContractTickCmdResponse,
            "time-series-data-update-request.json": ContractTimeSeriesDataUpdateRequest,
            "outflow-time-series-request.json": ContractOutflowTimeSeriesRequest,
            "agent-instance-status-report.json": ContractAgentInstanceStatusReport,
            "parameter-identified-report.json": ContractParameterIdentifiedReport,
            "hydro-alert-updated-report.json": ContractHydroAlertUpdatedReport,
        }

        for fixture_name, model in fixture_models.items():
            with self.subTest(fixture=fixture_name):
                payload = json.loads((self.FIXTURE_DIR / fixture_name).read_text())
                parsed = model.model_validate(payload)
                self.assertEqual(payload["command_type"], parsed.command_type)
                self.assertEqual(
                    payload["context_ref"]["biz_scene_instance_id"],
                    parsed.context_ref.biz_scene_instance_id,
                )

    def test_legacy_envelope_parses_canonical_task_init_response_fixture(self):
        payload = json.loads((self.FIXTURE_DIR / "task-init-response.json").read_text())
        backfilled = backfill_legacy_command_payload(payload)

        envelope = SimCommandEnvelope(command=backfilled)
        parsed = envelope.command

        self.assertIsInstance(parsed, LegacySimTaskInitResponse)
        self.assertEqual("agent-central-1", parsed.source_agent_instance.agent_id)
        self.assertEqual("agent-central-1", parsed.created_agent_instances[0].agent_id)
        self.assertEqual("bsi-1", parsed.context.biz_scene_instance_id)

    def test_first_batch_schema_resources_exist_and_are_valid_json(self):
        expected_schema_paths = [
            "common/agent-definition-ref.schema.json",
            "common/agent-instance-ref.schema.json",
            "common/command-envelope.schema.json",
            "common/task-context-ref.schema.json",
            "coordination/task-init-request.schema.json",
            "coordination/task-init-response.schema.json",
            "coordination/task-terminate-request.schema.json",
            "coordination/task-terminate-response.schema.json",
            "coordination/tick-cmd-request.schema.json",
            "coordination/tick-cmd-response.schema.json",
            "coordination/time-series-calculation-request.schema.json",
            "coordination/time-series-calculation-response.schema.json",
            "coordination/time-series-data-update-request.schema.json",
            "coordination/outflow-time-series-request.schema.json",
            "reports/agent-instance-status-report.schema.json",
            "reports/hydro-alert-updated-report.schema.json",
            "reports/parameter-identified-report.schema.json",
        ]

        for relative_path in expected_schema_paths:
            with self.subTest(schema=relative_path):
                schema_path = self.CONTRACT_DIR / relative_path
                self.assertTrue(schema_path.exists())
                schema = json.loads(schema_path.read_text())
                self.assertIn("$schema", schema)
                self.assertIn("required", schema)

    def test_contract_dictionaries_match_python_binding_constants(self):
        dictionary_dir = self.CONTRACT_DIR / "dictionaries"

        expected_command_types = [
            SIMCMD_TASK_INIT_REQUEST,
            SIMCMD_TASK_INIT_RESPONSE,
            SIMCMD_TASK_TERMINATE_REQUEST,
            SIMCMD_TASK_TERMINATE_RESPONSE,
            SIMCMD_TICK_CMD_REQUEST,
            SIMCMD_TICK_CMD_RESPONSE,
            SIMCMD_TIME_SERIES_CALCULATION_REQUEST,
            SIMCMD_TIME_SERIES_CALCULATION_RESPONSE,
            SIMCMD_TIME_SERIES_DATA_UPDATE_REQUEST,
            SIMCMD_OUTFLOW_TIME_SERIES_REQUEST,
            SIMCMD_AGENT_INSTANCE_STATUS_REPORT,
            SIMCMD_IDENTIFIED_PARAMS_REPORT,
            SIMCMD_HYDRO_ALERT_REPORT,
        ]
        expected_enums = {
            "command-types.json": expected_command_types,
            "command-status.json": [item.value for item in CommandStatus],
            "agent-status.json": [item.value for item in AgentStatus],
            "agent-instance-status.json": [item.value for item in AgentInstanceStatus],
            "agent-drive-mode.json": [item.value for item in AgentDriveMode],
        }

        for dictionary_name, expected_values in expected_enums.items():
            with self.subTest(dictionary=dictionary_name):
                dictionary = json.loads((dictionary_dir / dictionary_name).read_text())
                self.assertEqual(expected_values, dictionary["values"])


if __name__ == "__main__":
    unittest.main()
