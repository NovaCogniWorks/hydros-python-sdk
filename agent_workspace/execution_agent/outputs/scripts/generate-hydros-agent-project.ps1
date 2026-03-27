param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectName,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir,

    [string]$AgentClass = 'DemoTwinsAgent',
    [string]$AgentCode = 'DEMO_TWINS_AGENT',
    [string]$AgentType = 'TWINS_SIMULATION_AGENT',
    [ValidateSet('TwinsSimulationAgent', 'OntologySimulationAgent', 'CentralSchedulingAgent', 'ModelCalculationAgent', 'OutflowPlanAgent')]
    [string]$BaseClass = 'TwinsSimulationAgent',
    [ValidateSet('auto', 'twins', 'ontology', 'central')]
    [string]$Template = 'auto',
    [string]$SdkRoot
)

$ErrorActionPreference = 'Stop'

function Get-DefaultSdkRoot {
    $scriptDir = $PSScriptRoot
    $outputsDir = Split-Path -Parent $scriptDir
    $executionAgentDir = Split-Path -Parent $outputsDir
    $agentWorkspaceDir = Split-Path -Parent $executionAgentDir
    return Split-Path -Parent $agentWorkspaceDir
}

function Write-Utf8File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Content
    )

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content.TrimStart("`r", "`n") + "`n", $utf8NoBom)
}

function New-Directory {
    param([Parameter(Mandatory = $true)][string]$Path)

    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

if (-not $SdkRoot) {
    $SdkRoot = Get-DefaultSdkRoot
}

$resolvedSdkRoot = (Resolve-Path -Path $SdkRoot).ProviderPath
$resolvedOutputDir = [System.IO.Path]::GetFullPath($OutputDir)

if (-not (Test-Path (Join-Path $resolvedSdkRoot 'hydros_agent_sdk'))) {
    throw "Invalid SdkRoot: hydros_agent_sdk package not found under $resolvedSdkRoot"
}

$projectRoot = Join-Path $resolvedOutputDir $ProjectName
$agentAppDir = Join-Path $projectRoot 'agent_app'
$confDir = Join-Path $projectRoot 'conf'
$projectScriptsDir = Join-Path $projectRoot 'scripts'
$testsDir = Join-Path $projectRoot 'tests'

New-Directory -Path $projectRoot
New-Directory -Path $agentAppDir
New-Directory -Path $confDir
New-Directory -Path $projectScriptsDir
New-Directory -Path $testsDir

if ($Template -eq 'auto') {
    switch ($BaseClass) {
        'TwinsSimulationAgent' { $ScaffoldTemplate = 'twins' }
        'OntologySimulationAgent' { $ScaffoldTemplate = 'ontology' }
        'CentralSchedulingAgent' { $ScaffoldTemplate = 'central' }
        'ModelCalculationAgent' { $ScaffoldTemplate = 'central' }
        'OutflowPlanAgent' { $ScaffoldTemplate = 'central' }
        default { throw "Unsupported BaseClass for template auto: $BaseClass" }
    }
}
else {
    $ScaffoldTemplate = $Template
}

$twinsHydraulicSolverModule = ''
$twinsSimulationStatesModule = ''

switch ($ScaffoldTemplate) {
    'twins' {
        if ($BaseClass -ne 'TwinsSimulationAgent') {
            throw "Template 'twins' requires BaseClass 'TwinsSimulationAgent'. Current value: $BaseClass"
        }
    }
    'ontology' {
        if ($BaseClass -ne 'OntologySimulationAgent') {
            throw "Template 'ontology' requires BaseClass 'OntologySimulationAgent'. Current value: $BaseClass"
        }
    }
    'central' {
        if ($BaseClass -notin @('CentralSchedulingAgent', 'ModelCalculationAgent', 'OutflowPlanAgent')) {
            throw "Template 'central' requires BaseClass CentralSchedulingAgent, ModelCalculationAgent, or OutflowPlanAgent. Current value: $BaseClass"
        }
    }
}

$pyproject = @"
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "$ProjectName"
version = "0.1.0"
description = "Hydros external agent scaffold"
readme = "README.md"
requires-python = ">=3.11"
dependencies = ["paho-mqtt>=1.6,<3", "pydantic>=2,<3", "pyyaml>=6,<7"]

[tool.setuptools]
packages = ["agent_app"]

[tool.setuptools.package-dir]
agent_app = "agent_app"
"@

$readme = @"
# $ProjectName

This scaffold extracts the common engineering structure from the current twins, ontology, and pump scheduling agents. Selected template: $ScaffoldTemplate.

## Structure

- ``agent_app/user_logic.py``: primary business integration file for downstream users
- ``agent_app/runtime.py``: runtime bootstrap, logging, and client startup
- ``agent_app/support.py``: common lifecycle helpers and metrics conversion helpers
- ``agent_app/business_engine.py``: reusable adapter layer that delegates into ``user_logic.py``
- ``agent_app/agent_impl.py``: generated Agent implementation for the selected base class
- ``agent_app/hydraulic_solver.py``: twins template only, wraps ``corelib`` simulator integration
- ``agent_app/simulation_states.py``: twins template only, shared solver state definitions
- ``agent_app/service.py``: service entrypoint used by ``launcher.py``
- ``conf/env.properties``: node and MQTT configuration
- ``conf/agent.properties``: agent identity and scaffold parameters
- ``scripts/bootstrap.ps1``: create ``.venv`` and link local source paths
- ``scripts/run.ps1``: start the generated service
- ``tests/test_scaffold_import.py``: smoke test for imports and config loading

## Quick Start

``````powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
.\.venv\Scripts\python.exe -m unittest tests.test_scaffold_import
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
``````

## Run Modes

- ``solver_backend=dry_run``: starts immediately, can connect to MQTT/cloud coordination, and returns deterministic placeholder hydraulic results.
- ``solver_backend=corelib``: downloads the remote IDZ YAML and calls the real ``corelib`` simulator.

## Extension Points

- Put domain behavior into ``agent_app/user_logic.py``
- Keep ``agent_app/business_engine.py`` as the adapter layer unless you need advanced runtime customization
- Keep lifecycle and runtime assembly inside ``agent_app/runtime.py`` and ``agent_app/support.py``
- Extend protocol-specific hooks in ``agent_app/agent_impl.py``

## Notes

- ``bootstrap.ps1`` links the generated project root and the SDK source root into the virtual environment through a ``.pth`` file.
- If the host Python environment does not already provide ``paho-mqtt``, ``pydantic``, and ``pyyaml``, install them into ``.venv``.
- For twins projects, configure ``corelib_package_root`` and ``idz_config_url`` before connecting to the real algorithm runtime.
"@

$envProps = @"
# MQTT broker settings
mqtt_broker_url=tcp://127.0.0.1
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/{hydros_cluster_id}

# Hydros node identity
hydros_cluster_id=default_cluster
hydros_node_id=external_node_001

# Optional MQTT auth
mqtt_username=
mqtt_password=

# Optional metrics topic for central scheduling style agents
metrics_topic=/hydros/metrics/{hydros_cluster_id}
"@

$agentProps = @"
# Hydros agent identity
agent_code=$AgentCode
agent_type=$AgentType
agent_name=$AgentClass

# Optional scaffold parameters
boundary_condition_metrics=inflow,upstream_water_level
reasoning_mode=forward_chaining
optimization_horizon=5
"@

switch ($ScaffoldTemplate) {
    'twins' {
        $agentProps = @"
# Hydros agent identity
agent_code=$AgentCode
agent_type=$AgentType
agent_name=$AgentClass

# Twins scaffold parameters
time_step=60
convergence_tolerance=1e-6
max_iterations=100
boundary_condition_metrics=inflow,upstream_water_level
solver_mode=hydraulic
solver_backend=dry_run
idz_config_url=https://replace-with-idz-config.example.com/idz.yml
corelib_package_root=C:/replace-with-corelib-parent
idz_local_cache_dir=data
"@

        $readme += @"

## Template Notes: Twins

- Default parameters target time-step simulation and boundary-condition driven twins execution.
- The generated project starts in ``solver_backend=dry_run`` mode, so it can connect to MQTT/cloud coordination before the real algorithm library is wired in.
- Switch ``solver_backend`` to ``corelib`` when you are ready to call ``corelib.core.hydro_simulator.HydroSimulator`` through ``agent_app/hydraulic_solver.py``.
- Set ``corelib_package_root`` to the parent directory of the ``corelib`` package, and set ``idz_config_url`` to the remote YAML used by the solver.
- Use ``boundary_condition_metrics``, ``time_step``, ``convergence_tolerance``, ``max_iterations``, ``solver_backend``, ``idz_config_url``, and ``corelib_package_root`` in ``conf/agent.properties``.
"@
    }
    'ontology' {
        $agentProps = @"
# Hydros agent identity
agent_code=$AgentCode
agent_type=$AgentType
agent_name=$AgentClass

# Ontology scaffold parameters
reasoning_mode=forward_chaining
rule_file=
inference_depth=3
boundary_condition_metrics=inflow,upstream_water_level
ontology_profile=water_network
"@

        $readme += @"

## Template Notes: Ontology

- Default parameters target rule-engine based reasoning and lightweight boundary-condition input.
- Put ontology loading and rule execution into ``agent_app/user_logic.py``.
- Use ``reasoning_mode``, ``rule_file``, and ``inference_depth`` in ``conf/agent.properties``.
"@
    }
    'central' {
        $envProps += @"

# Central scheduling template settings
control_command_topic=/hydros/commands/control/{hydros_cluster_id}
"@

        if ($BaseClass -eq 'CentralSchedulingAgent') {
            $agentProps = @"
# Hydros agent identity
agent_code=$AgentCode
agent_type=$AgentType
agent_name=$AgentClass

# Central scheduling scaffold parameters
optimization_horizon=5
metrics_topic_enabled=true
command_batch_size=10
control_mode=rolling_horizon
"@
        }
        elseif ($BaseClass -eq 'ModelCalculationAgent') {
            $agentProps = @"
# Hydros agent identity
agent_code=$AgentCode
agent_type=$AgentType
agent_name=$AgentClass

# Model calculation scaffold parameters
calculation_mode=event_driven
accepted_event_types=TimeSeriesDataUpdateRequest,ModelCalculation
result_metrics_code=generated_metric
"@
        }
        else {
            $agentProps = @"
# Hydros agent identity
agent_code=$AgentCode
agent_type=$AgentType
agent_name=$AgentClass

# Outflow planning scaffold parameters
plan_window=24
outflow_metric_code=outflow_time_series
publish_plan_metrics=true
"@
        }

        $readme += @"

## Template Notes: Central

- This template covers ``CentralSchedulingAgent``, ``ModelCalculationAgent``, and ``OutflowPlanAgent`` style scaffolds.
- ``env.properties`` includes control topics aligned with scheduling-style agents.
- ``agent.properties`` defaults change based on the selected base class so the generated config is closer to the runtime role, while users still mainly edit ``agent_app/user_logic.py``.
"@
    }
}

$initPy = @"
"""Generated Hydros agent scaffold package."""

from agent_app.agent_impl import $AgentClass

__all__ = ["$AgentClass"]
"@

$businessEngine = @"
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_app.user_logic import UserLogic


@dataclass(slots=True)
class StepExecutionResult:
    step: int
    state: dict[str, Any] = field(default_factory=dict)
    metrics: list[dict[str, Any]] = field(default_factory=list)


class BaseGeneratedBusinessEngine:
    """Runtime adapter that delegates domain behavior to agent_app.user_logic."""

    def __init__(self) -> None:
        self.logic = UserLogic()

    def initialize(self, context: Any, properties: Any = None, topology: Any = None) -> None:
        self.context = context
        self.properties = properties
        self.topology = topology
        self.logic.initialize(context=context, properties=properties, topology=topology)

    def collect_boundary_conditions(self, step: int, agent: Any) -> dict[int, dict[str, Any]]:
        return self.logic.collect_boundary_conditions(step=step, agent=agent)

    def execute_step(
        self,
        step: int,
        payload: dict[str, Any] | None = None,
        boundary_conditions: dict[int, dict[str, Any]] | None = None,
    ) -> StepExecutionResult:
        return StepExecutionResult(step=step)

    def handle_event(
        self,
        event_name: str,
        payload: dict[str, Any] | None = None,
        agent: Any = None,
    ) -> list[dict[str, Any]]:
        return self.logic.handle_event(event_name=event_name, payload=payload or {}, agent=agent)

    def simulate_twins_step(
        self,
        step: int,
        boundary_conditions: dict[int, dict[str, Any]] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> StepExecutionResult:
        return self.execute_step(step=step, payload=payload, boundary_conditions=boundary_conditions)

    def run_ontology_reasoning(
        self,
        step: int,
        boundary_conditions: dict[int, dict[str, Any]] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> StepExecutionResult:
        return self.execute_step(step=step, payload=payload, boundary_conditions=boundary_conditions)

    def build_dispatch_plan(
        self,
        step: int,
        payload: dict[str, Any] | None = None,
    ) -> StepExecutionResult:
        return self.execute_step(step=step, payload=payload, boundary_conditions=None)

    def process_time_series_update(self, request: Any, agent: Any = None) -> list[dict[str, Any]]:
        return self.handle_event('time_series_data_update', {'request': request}, agent=agent)

    def process_outflow_update(self, request: Any, agent: Any = None) -> list[dict[str, Any]]:
        return self.handle_event('outflow_time_series_data_update', {'request': request}, agent=agent)

    def process_model_calculation(self, hydro_event: Any, agent: Any = None) -> list[dict[str, Any]]:
        return self.handle_event('model_calculation', {'event': hydro_event}, agent=agent)

    def process_outflow_plan(self, request: Any, agent: Any = None) -> list[dict[str, Any]]:
        return self.handle_event('outflow_time_series', {'request': request}, agent=agent)

    def shutdown(self) -> None:
        self.logic.shutdown()
"@

switch ($ScaffoldTemplate) {
    'twins' {
        $businessEngine += @"

class DemoBusinessEngine(BaseGeneratedBusinessEngine):
    """Twins adapter: users only implement domain logic in user_logic.py."""

    def initialize(self, context: Any, properties: Any = None, topology: Any = None) -> None:
        super().initialize(context, properties, topology)
        self.time_step = int(getattr(properties, 'get_property', lambda *args, **kwargs: 60)('time_step', 60))
        self.convergence_tolerance = float(
            getattr(properties, 'get_property', lambda *args, **kwargs: 1e-6)('convergence_tolerance', 1e-6)
        )
        self.max_iterations = int(getattr(properties, 'get_property', lambda *args, **kwargs: 100)('max_iterations', 100))

    def simulate_twins_step(
        self,
        step: int,
        boundary_conditions: dict[int, dict[str, Any]] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> StepExecutionResult:
        result = self.logic.simulate_twins_step(
            step=step,
            payload=payload or {},
            boundary_conditions=boundary_conditions or {},
        )
        result.state.setdefault('mode', 'twins')
        result.state.setdefault('time_step', self.time_step)
        result.state.setdefault('convergence_tolerance', self.convergence_tolerance)
        result.state.setdefault('max_iterations', self.max_iterations)
        result.state.setdefault('biz_scene_instance_id', getattr(self.context, 'biz_scene_instance_id', ''))
        return result
"@

        $userLogicModule = @"
from __future__ import annotations

import logging
from typing import Any

from agent_app.hydraulic_solver import HydraulicSolver

logger = logging.getLogger(__name__)


class UserLogic:
    """Twins user logic backed by the generated corelib hydraulic solver wrapper."""

    def initialize(self, context: Any, properties: Any = None, topology: Any = None) -> None:
        self.context = context
        self.properties = properties
        self.topology = topology
        self._hydraulic_solver = HydraulicSolver.get_or_create(getattr(context, 'biz_scene_instance_id', 'default_job'))
        self.solver_backend = str(self._get_property('solver_backend', 'dry_run')).strip().lower()
        self._hydraulic_solver.configure(
            time_step=int(self._get_property('time_step', 60)),
            convergence_tolerance=float(self._get_property('convergence_tolerance', 1e-6)),
            max_iterations=int(self._get_property('max_iterations', 100)),
            corelib_package_root=self._get_property('corelib_package_root', ''),
            idz_local_cache_dir=self._get_property('idz_local_cache_dir', 'data'),
        )
        if self.solver_backend == 'corelib':
            self._hydraulic_solver.initialize(
                topology=topology,
                idz_config_url=self._get_property('idz_config_url', ''),
            )
        else:
            logger.info('solver_backend=%s, starting generated twins project in dry-run mode', self.solver_backend)
            self._hydraulic_solver.initialize(topology=topology, idz_config_url='')

    def _get_property(self, key: str, default: Any = None) -> Any:
        if self.properties is None:
            return default
        getter = getattr(self.properties, 'get_property', None)
        if getter is None:
            return default
        return getter(key, default)

    def collect_boundary_conditions(self, step: int, agent: Any) -> dict[int, dict[str, Any]]:
        return {}

    def simulate_twins_step(
        self,
        step: int,
        payload: dict[str, Any],
        boundary_conditions: dict[int, dict[str, Any]],
    ):
        from agent_app.business_engine import StepExecutionResult

        results = self._hydraulic_solver.solve_step(step=step, boundary_conditions=boundary_conditions)
        metrics = self._hydraulic_solver.convert_results_to_metrics(
            results,
            default_object_name=payload.get('object_name', 'GeneratedObject'),
        )
        return StepExecutionResult(
            step=step,
            state={
                'status': 'ok',
                'solver_mode': self._get_property('solver_mode', 'hydraulic'),
                'solver_backend': self.solver_backend,
                'result_object_count': len(results),
            },
            metrics=metrics,
        )

    def handle_event(self, event_name: str, payload: dict[str, Any], agent: Any = None) -> list[dict[str, Any]]:
        if event_name == 'boundary_condition_update':
            logger.info('Received %s boundary-condition series for synchronization', len(payload.get('time_series', [])))
        return [{'event_name': event_name, 'payload_keys': sorted(payload.keys())}]

    def shutdown(self) -> None:
        HydraulicSolver.remove(getattr(self.context, 'biz_scene_instance_id', 'default_job'))
        return None
"@

        $twinsSimulationStatesModule = @"
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DeviceControl:
    device_name: str
    e_i_t: float
    n_i_t: int
    target_flow: float = 0.0


@dataclass(slots=True)
class BoundaryState:
    h_i_t: float = 0.0
    hat_h_i_t: float = 0.0
    inflow_i_t: float = 0.0
    Inflow_i_t: float = 0.0
    qtot_i_t: float = 0.0
    boundary_type: str = 'default'
    boundary_id: str = ''


@dataclass(slots=True)
class SolverConfiguration:
    time_step: int = 60
    convergence_tolerance: float = 1e-6
    max_iterations: int = 100
    corelib_package_root: str = ''
    idz_local_cache_dir: str = 'data'


@dataclass(slots=True)
class SolverRuntimeState:
    job_instance_id: str
    controls: dict[int, dict[str, DeviceControl]] = field(default_factory=dict)
    boundary_params: dict[int, dict[str, BoundaryState]] = field(default_factory=dict)
    simulation_states: dict[int, object] = field(default_factory=dict)
"@

        $twinsHydraulicSolverModule = @"
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse, urlunparse
from urllib.request import Request, urlopen

from agent_app.simulation_states import BoundaryState, DeviceControl, SolverConfiguration, SolverRuntimeState

logger = logging.getLogger(__name__)


class HydraulicSolver:
    """Hydraulic solver wrapper aligned with the reference twins implementation."""

    _solvers: dict[str, 'HydraulicSolver'] = {}
    _lock = threading.RLock()

    @classmethod
    def get_or_create(cls, job_instance_id: str) -> 'HydraulicSolver':
        with cls._lock:
            solver = cls._solvers.get(job_instance_id)
            if solver is None:
                solver = cls(job_instance_id)
                cls._solvers[job_instance_id] = solver
            return solver

    @classmethod
    def remove(cls, job_instance_id: str) -> None:
        with cls._lock:
            solver = cls._solvers.pop(job_instance_id, None)
        if solver is not None:
            solver.cleanup()

    def __init__(self, job_instance_id: str) -> None:
        self.job_instance_id = job_instance_id
        self.config = SolverConfiguration()
        self.runtime = SolverRuntimeState(job_instance_id=job_instance_id)
        self.sim: Any | None = None
        self._hydro_simulator_cls: Any | None = None
        self._initialized = False

    def configure(
        self,
        *,
        time_step: int,
        convergence_tolerance: float,
        max_iterations: int,
        corelib_package_root: str,
        idz_local_cache_dir: str,
    ) -> None:
        self.config = SolverConfiguration(
            time_step=time_step,
            convergence_tolerance=convergence_tolerance,
            max_iterations=max_iterations,
            corelib_package_root=corelib_package_root,
            idz_local_cache_dir=idz_local_cache_dir,
        )

    def initialize(self, topology: Any, idz_config_url: str) -> None:
        if not self._is_runtime_ready(idz_config_url):
            return

        self._ensure_corelib_import()
        config_file = self._download_idz_config(idz_config_url)
        self.sim = self._hydro_simulator_cls(config_file)

        initial_states = dict(self.sim.get_initial_states())
        self.runtime.simulation_states = dict(initial_states)
        self._prepare_runtime_state(topology=topology, initial_states=initial_states)
        self._initialized = True

        logger.info(
            'HydraulicSolver initialized: job=%s, nodes=%s, controls=%s, boundaries=%s',
            self.job_instance_id,
            len(self.runtime.simulation_states),
            len(self.runtime.controls),
            len(self.runtime.boundary_params),
        )

    def solve_step(self, step: int, boundary_conditions: dict[int, dict[str, Any]]) -> dict[int, dict[str, float]]:
        if not self._initialized or self.sim is None:
            logger.info('HydraulicSolver not initialized, using dry-run results for step=%s', step)
            return self._dry_run_results(step=step, boundary_conditions=boundary_conditions)

        self._apply_boundary_conditions(boundary_conditions)
        logger.info(
            'Executing corelib solve_step: step=%s, boundary_objects=%s',
            step,
            len(boundary_conditions),
        )
        new_states, _ = self.sim.step(
            controls=self.runtime.controls,
            boundary_params=self.runtime.boundary_params,
            simulation_states=self.runtime.simulation_states,
        )
        self.runtime.simulation_states = dict(new_states)

        output_results: dict[int, dict[str, float]] = {}
        for node_id, state in new_states.items():
            station_state = getattr(state, 'station_state', None)
            if station_state is None:
                continue
            output_results[int(node_id)] = {
                'water_level': float(getattr(station_state, 'h_i_t', 0.0)),
                'water_flow': float(getattr(station_state, 'qtot_i_t', 0.0)),
            }

        logger.info('Corelib solve_step completed: step=%s, output_nodes=%s', step, len(output_results))
        return output_results

    def convert_results_to_metrics(
        self,
        results: dict[int, dict[str, float]],
        *,
        default_object_name: str,
    ) -> list[dict[str, Any]]:
        metrics: list[dict[str, Any]] = []
        for object_id, values in results.items():
            object_name = f'{default_object_name}_{object_id}'
            for metrics_code, value in values.items():
                metrics.append(
                    {
                        'object_id': object_id,
                        'object_name': object_name,
                        'metrics_code': metrics_code,
                        'value': float(value),
                    }
                )
        return metrics

    def cleanup(self) -> None:
        cleanup = getattr(self.sim, 'cleanup', None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception as exc:
                logger.warning('corelib cleanup failed: %s', exc, exc_info=True)
        self.sim = None
        self._initialized = False

    def _ensure_corelib_import(self) -> None:
        if self._hydro_simulator_cls is not None:
            return

        package_root = self.config.corelib_package_root.strip()
        if package_root:
            resolved = str(Path(package_root).expanduser().resolve())
            if resolved not in sys.path:
                sys.path.insert(0, resolved)

        try:
            from corelib.core.hydro_simulator import HydroSimulator  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                'Failed to import corelib HydroSimulator. Set corelib_package_root in conf/agent.properties to the parent directory of the corelib package.'
            ) from exc

        self._hydro_simulator_cls = HydroSimulator

    def _prepare_runtime_state(self, topology: Any, initial_states: dict[int, Any]) -> None:
        self.runtime.controls = {}
        self.runtime.boundary_params = {}

        for node_id, state in initial_states.items():
            node_key = int(node_id)
            device_states = getattr(state, 'device_states', {}) or {}
            self.runtime.controls[node_key] = {}
            for device_name in device_states.keys():
                self.runtime.controls[node_key][str(device_name)] = DeviceControl(
                    device_name=str(device_name),
                    e_i_t=65.0,
                    n_i_t=1,
                )
            self.runtime.boundary_params[node_key] = {
                'upstream_boundary': BoundaryState(boundary_type='upstream', boundary_id=str(node_key)),
                'downstream_boundary': BoundaryState(boundary_type='downstream', boundary_id=str(node_key)),
            }

        if topology is None:
            return

        for top_obj in getattr(topology, 'top_objects', []):
            for child in getattr(top_obj, 'children', []):
                object_id = int(child.object_id)
                self.runtime.controls.setdefault(object_id, {})
                self.runtime.boundary_params.setdefault(
                    object_id,
                    {
                        'upstream_boundary': BoundaryState(boundary_type='upstream', boundary_id=str(object_id)),
                        'downstream_boundary': BoundaryState(boundary_type='downstream', boundary_id=str(object_id)),
                    },
                )

    def _is_runtime_ready(self, idz_config_url: str) -> bool:
        normalized_url = idz_config_url.strip()
        if not normalized_url:
            logger.warning('idz_config_url is empty; solver will stay in dry-run mode until configured.')
            return False
        if self._is_placeholder_value(normalized_url):
            logger.warning('idz_config_url still uses a placeholder value; solver will stay in dry-run mode.')
            return False

        package_root = self.config.corelib_package_root.strip()
        if not package_root:
            logger.warning('corelib_package_root is empty; solver will stay in dry-run mode until configured.')
            return False
        if self._is_placeholder_value(package_root):
            logger.warning('corelib_package_root still uses a placeholder value; solver will stay in dry-run mode.')
            return False

        resolved_root = Path(package_root).expanduser()
        if not resolved_root.exists():
            logger.warning(
                'corelib_package_root=%s does not exist; solver will stay in dry-run mode.',
                resolved_root,
            )
            return False
        return True

    @staticmethod
    def _is_placeholder_value(value: str) -> bool:
        normalized = value.strip().lower()
        return 'replace-with' in normalized or normalized.endswith('.example.com/idz.yml')

    def _apply_boundary_conditions(self, boundary_conditions: dict[int, dict[str, Any]]) -> None:
        for object_id, values in boundary_conditions.items():
            boundaries = self.runtime.boundary_params.setdefault(int(object_id), {})
            upstream = boundaries.setdefault('upstream_boundary', BoundaryState(boundary_type='upstream', boundary_id=str(object_id)))
            downstream = boundaries.setdefault('downstream_boundary', BoundaryState(boundary_type='downstream', boundary_id=str(object_id)))
            for boundary in (upstream, downstream):
                boundary.h_i_t = float(values.get('h_i_t', values.get('upstream_water_level', boundary.h_i_t)))
                boundary.inflow_i_t = float(values.get('Inflow_i_t', values.get('inflow', boundary.inflow_i_t)))
                boundary.qtot_i_t = float(values.get('qtot_i_t', values.get('water_flow', boundary.qtot_i_t)))

    def _dry_run_results(self, step: int, boundary_conditions: dict[int, dict[str, Any]]) -> dict[int, dict[str, float]]:
        if not boundary_conditions:
            return {1: {'water_level': float(step), 'water_flow': 0.0}}

        output_results: dict[int, dict[str, float]] = {}
        for object_id, values in boundary_conditions.items():
            output_results[int(object_id)] = {
                'water_level': float(values.get('upstream_water_level', values.get('h_i_t', step))),
                'water_flow': float(values.get('inflow', values.get('qtot_i_t', 0.0))),
            }
        return output_results

    def _download_idz_config(self, idz_config_url: str) -> str:
        parsed = urlparse(idz_config_url)
        encoded_path = quote(unquote(parsed.path), safe="/:@!$&'()*+,;=")
        encoded_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            encoded_path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        ))

        request = Request(encoded_url)
        request.add_header('User-Agent', 'Hydros-Agent-SDK/GeneratedTwinsScaffold')
        try:
            with urlopen(request, timeout=30) as response:
                content = response.read().decode('utf-8')
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f'Failed to download IDZ config from {idz_config_url}: {exc}') from exc

        content = self._normalize_idz_yaml(content)

        cache_dir = Path(self.config.idz_local_cache_dir).expanduser()
        if not cache_dir.is_absolute():
            cache_dir = Path(__file__).resolve().parents[1] / cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

        output_path = cache_dir / f'idz_config_{self.job_instance_id}.yml'
        output_path.write_text(content, encoding='utf-8')
        logger.info('IDZ config saved to %s', output_path)
        return str(output_path)

    def _normalize_idz_yaml(self, content: str) -> str:
        try:
            import yaml
        except ImportError:
            logger.warning('PyYAML is not installed, skipping IDZ YAML normalization.')
            return content

        try:
            data = yaml.safe_load(content)
        except Exception as exc:
            logger.warning('Failed to parse IDZ YAML for normalization: %s', exc, exc_info=True)
            return content

        if isinstance(data, dict) and 'objects' in data and 'components' not in data:
            data['components'] = data.pop('objects')
            logger.info("Normalized downloaded IDZ YAML: renamed top-level 'objects' to 'components'.")

        return yaml.safe_dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
"@
    }
    'ontology' {
        $businessEngine += @"

class DemoBusinessEngine(BaseGeneratedBusinessEngine):
    """Ontology adapter: users only implement reasoning logic in user_logic.py."""

    def initialize(self, context: Any, properties: Any = None, topology: Any = None) -> None:
        super().initialize(context, properties, topology)
        self.reasoning_mode = getattr(properties, 'get_property', lambda *args, **kwargs: 'forward_chaining')(
            'reasoning_mode',
            'forward_chaining',
        )
        self.inference_depth = int(getattr(properties, 'get_property', lambda *args, **kwargs: 3)('inference_depth', 3))

    def run_ontology_reasoning(
        self,
        step: int,
        boundary_conditions: dict[int, dict[str, Any]] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> StepExecutionResult:
        result = self.logic.run_ontology_reasoning(
            step=step,
            payload=payload or {},
            boundary_conditions=boundary_conditions or {},
        )
        result.state.setdefault('mode', 'ontology')
        result.state.setdefault('reasoning_mode', self.reasoning_mode)
        result.state.setdefault('inference_depth', self.inference_depth)
        result.state.setdefault('biz_scene_instance_id', getattr(self.context, 'biz_scene_instance_id', ''))
        return result
"@

        $userLogicModule = @"
from __future__ import annotations

from typing import Any


class UserLogic:
    """Edit this file first. Keep your ontology/rule logic here."""

    def initialize(self, context: Any, properties: Any = None, topology: Any = None) -> None:
        self.context = context
        self.properties = properties
        self.topology = topology

    def collect_boundary_conditions(self, step: int, agent: Any) -> dict[int, dict[str, Any]]:
        return {}

    def run_ontology_reasoning(
        self,
        step: int,
        payload: dict[str, Any],
        boundary_conditions: dict[int, dict[str, Any]],
    ):
        from agent_app.business_engine import StepExecutionResult

        metrics = [
            {
                'object_id': payload.get('object_id', 1),
                'object_name': payload.get('object_name', 'GeneratedObject'),
                'metrics_code': 'ontology_inference_score',
                'value': 1.0,
            }
        ]
        return StepExecutionResult(step=step, state={'status': 'ok'}, metrics=metrics)

    def handle_event(self, event_name: str, payload: dict[str, Any], agent: Any = None) -> list[dict[str, Any]]:
        return [{'event_name': event_name, 'payload_keys': sorted(payload.keys())}]

    def shutdown(self) -> None:
        return None
"@
    }
    'central' {
        $businessEngine += @"

class DemoBusinessEngine(BaseGeneratedBusinessEngine):
    """Central adapter: users only implement scheduling/event logic in user_logic.py."""

    def initialize(self, context: Any, properties: Any = None, topology: Any = None) -> None:
        super().initialize(context, properties, topology)
        self.optimization_horizon = int(getattr(properties, 'get_property', lambda *args, **kwargs: 5)('optimization_horizon', 5))

    def build_dispatch_plan(self, step: int, payload: dict[str, Any] | None = None) -> StepExecutionResult:
        result = self.logic.build_dispatch_plan(step=step, payload=payload or {})
        result.state.setdefault('mode', 'central')
        result.state.setdefault('optimization_horizon', self.optimization_horizon)
        result.state.setdefault('biz_scene_instance_id', getattr(self.context, 'biz_scene_instance_id', ''))
        return result
"@

        $userLogicModule = @"
from __future__ import annotations

from typing import Any


class UserLogic:
    """Edit this file first. Keep your scheduling/calculation/planning logic here."""

    def initialize(self, context: Any, properties: Any = None, topology: Any = None) -> None:
        self.context = context
        self.properties = properties
        self.topology = topology

    def collect_boundary_conditions(self, step: int, agent: Any) -> dict[int, dict[str, Any]]:
        return {}

    def build_dispatch_plan(self, step: int, payload: dict[str, Any]):
        from agent_app.business_engine import StepExecutionResult

        commands = payload.get('commands') or [
            {
                'target_agent': 'DOWNSTREAM_AGENT',
                'command_type': 'generated_control_command',
                'parameters': {'step': step},
            }
        ]
        metrics = [
            {
                'object_id': payload.get('object_id', 1),
                'object_name': payload.get('object_name', 'GeneratedController'),
                'metrics_code': 'dispatch_count',
                'value': float(len(commands)),
            }
        ]
        return StepExecutionResult(step=step, state={'status': 'ok', 'commands': commands}, metrics=metrics)

    def handle_event(self, event_name: str, payload: dict[str, Any], agent: Any = None) -> list[dict[str, Any]]:
        return [{'event_name': event_name, 'payload_keys': sorted(payload.keys())}]

    def shutdown(self) -> None:
        return None
"@
    }
}
$supportModule = @"
from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

from hydros_agent_sdk.protocol.commands import (
    OutflowTimeSeriesDataUpdateResponse,
    SimTaskInitResponse,
    SimTaskTerminateResponse,
    TimeSeriesDataUpdateResponse,
)
from hydros_agent_sdk.protocol.models import AgentBizStatus, CommandStatus
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics, create_mock_metrics

logger = logging.getLogger(__name__)


def initialize_engine(agent: Any) -> None:
    agent.engine.initialize(
        context=agent.context,
        properties=getattr(agent, 'properties', None),
        topology=getattr(agent, '_topology', None),
    )


def shutdown_engine(agent: Any) -> None:
    try:
        agent.engine.shutdown()
    except Exception as exc:
        logger.warning('Business engine shutdown failed: %s', exc, exc_info=True)


def register_local_agent(agent: Any, request: Any) -> SimTaskInitResponse:
    agent.load_agent_configuration(request)
    initialize_engine(agent)
    agent.state_manager.init_task(agent.context, [agent])
    agent.state_manager.add_local_agent(agent)
    object.__setattr__(agent, 'agent_biz_status', AgentBizStatus.ACTIVE)
    return SimTaskInitResponse(
        context=agent.context,
        command_id=request.command_id,
        command_status=CommandStatus.SUCCEED,
        source_agent_instance=agent,
        created_agent_instances=[agent],
        managed_top_objects={},
        broadcast=False,
    )


def unregister_local_agent(agent: Any, request: Any) -> SimTaskTerminateResponse:
    shutdown_engine(agent)
    agent.state_manager.terminate_task(agent.context)
    agent.state_manager.remove_local_agent(agent)
    return SimTaskTerminateResponse(
        context=agent.context,
        command_id=request.command_id,
        command_status=CommandStatus.SUCCEED,
        source_agent_instance=agent,
        broadcast=False,
    )


def time_series_update_response(agent: Any, request: Any) -> TimeSeriesDataUpdateResponse:
    return TimeSeriesDataUpdateResponse(
        context=agent.context,
        command_id=request.command_id,
        command_status=CommandStatus.SUCCEED,
        source_agent_instance=agent,
        broadcast=False,
    )


def outflow_update_response(agent: Any, request: Any) -> OutflowTimeSeriesDataUpdateResponse:
    return OutflowTimeSeriesDataUpdateResponse(
        context=agent.context,
        command_id=request.command_id,
        command_status=CommandStatus.SUCCEED,
        source_agent_instance=agent,
        broadcast=False,
    )


def collect_boundary_conditions(agent: Any, step: int, metrics_codes: Iterable[str]) -> dict[int, dict[str, Any]]:
    topology = getattr(agent, '_topology', None)
    if topology is None:
        return {}

    boundary_conditions: dict[int, dict[str, Any]] = {}
    for top_obj in getattr(topology, 'top_objects', []):
        for child in getattr(top_obj, 'children', []):
            object_bc: dict[str, Any] = {}
            for metrics_code in metrics_codes:
                value = agent.get_time_series_value(child.object_id, metrics_code, step)
                if value is not None:
                    object_bc[metrics_code] = value
            if object_bc:
                boundary_conditions[child.object_id] = object_bc
    return boundary_conditions


def build_metric_messages(agent: Any, step: int, metrics: Iterable[Mapping[str, Any]]) -> list[MqttMetrics]:
    messages: list[MqttMetrics] = []
    for metric in metrics:
        object_id = int(metric.get('object_id', 1))
        object_name = str(metric.get('object_name', f'Object_{object_id}'))
        metrics_code = str(metric.get('metrics_code', 'generated_metric'))
        value = metric.get('value', 0)
        messages.append(
            create_mock_metrics(
                source_id=agent.agent_code,
                job_instance_id=agent.biz_scene_instance_id,
                object_id=object_id,
                object_name=object_name,
                step_index=step,
                metrics_code=metrics_code,
                value=value,
            )
        )
    return messages
"@

$runtimeModule = @"
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Type

from hydros_agent_sdk import (
    HydroAgentFactory,
    MultiAgentCallback,
    SimCoordinationClient,
    load_agent_config,
    load_env_config,
    setup_logging,
)
from hydros_agent_sdk.base_agent import BaseHydroAgent

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    project_root: Path
    conf_dir: Path
    log_dir: Path
    env_file: Path
    agent_file: Path


def discover_paths() -> ProjectPaths:
    project_root = Path(__file__).resolve().parents[1]
    conf_dir = project_root / 'conf'
    log_dir = project_root / 'logs'
    return ProjectPaths(
        project_root=project_root,
        conf_dir=conf_dir,
        log_dir=log_dir,
        env_file=conf_dir / 'env.properties',
        agent_file=conf_dir / 'agent.properties',
    )


def load_project_env_config(paths: ProjectPaths) -> dict[str, str]:
    return load_env_config(str(paths.env_file.resolve()))


def load_project_agent_config(paths: ProjectPaths) -> dict[str, str]:
    return load_agent_config(str(paths.agent_file.resolve()))

def configure_project_logging(paths: ProjectPaths, env_config: dict[str, str]) -> None:
    paths.log_dir.mkdir(exist_ok=True)
    setup_logging(
        hydros_cluster_id=env_config['hydros_cluster_id'],
        hydros_node_id=env_config['hydros_node_id'],
        log_file=str((paths.log_dir / 'hydros-agent.log').resolve()),
    )


def create_coordination_client(
    agent_class: Type[BaseHydroAgent],
    env_config: dict[str, str],
    agent_config: dict[str, str],
    paths: ProjectPaths,
) -> SimCoordinationClient:
    factory = HydroAgentFactory(
        agent_class=agent_class,
        config_file=str(paths.agent_file.resolve()),
        env_config=env_config,
    )
    callback = MultiAgentCallback(node_id=env_config['hydros_node_id'])

    agent_code = agent_config['agent_code']
    agent_type = agent_config['agent_type']
    callback.register_agent_factory(agent_code, factory)
    if agent_type != agent_code:
        callback.register_agent_factory(agent_type, factory)
    client = SimCoordinationClient(
        broker_url=env_config['mqtt_broker_url'],
        broker_port=int(env_config['mqtt_broker_port']),
        topic=env_config['mqtt_topic'],
        sim_coordination_callback=callback,
        mqtt_username=env_config.get('mqtt_username'),
        mqtt_password=env_config.get('mqtt_password'),
    )
    callback.set_client(client)
    return client


def run_agent_service(
    agent_class: Type[BaseHydroAgent],
    service_name: str,
) -> None:
    paths = discover_paths()
    env_config = load_project_env_config(paths)
    agent_config = load_project_agent_config(paths)
    configure_project_logging(paths, env_config)
    client = create_coordination_client(agent_class, env_config, agent_config, paths)

    logger.info('=' * 70)
    logger.info('Starting %s', service_name)
    logger.info('Environment config: %s', paths.env_file)
    logger.info('Agent config: %s', paths.agent_file)
    logger.info('Configured Agent Code: %s', agent_config['agent_code'])
    logger.info('Configured Agent Type: %s', agent_config['agent_type'])
    logger.info('MQTT Broker: %s:%s', env_config['mqtt_broker_url'], env_config['mqtt_broker_port'])
    logger.info('MQTT Topic: %s', env_config['mqtt_topic'])
    logger.info('=' * 70)

    client.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info('Stopping service due to keyboard interrupt')
        client.stop()
"@

$serviceModule = @"
from agent_app.agent_impl import $AgentClass
from agent_app.runtime import run_agent_service


def main() -> None:
    run_agent_service(
        agent_class=$AgentClass,
        service_name='$ProjectName / $BaseClass',
    )


if __name__ == '__main__':
    main()
"@

switch ($BaseClass) {
    'TwinsSimulationAgent' {
        $agentImpl = @"
from __future__ import annotations

import logging
from typing import List

from hydros_agent_sdk import $BaseClass
from hydros_agent_sdk.protocol.commands import SimTaskTerminateRequest, SimTaskTerminateResponse
from hydros_agent_sdk.protocol.models import ObjectTimeSeries
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics

from agent_app.business_engine import DemoBusinessEngine
from agent_app.support import build_metric_messages, collect_boundary_conditions, shutdown_engine

logger = logging.getLogger(__name__)


class $AgentClass($BaseClass):
    """Generated twins-style agent scaffold with engine/runtime separation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.engine = DemoBusinessEngine()

    def _initialize_twins_model(self) -> None:
        self.engine.initialize(
            context=self.context,
            properties=self.properties,
            topology=getattr(self, '_topology', None),
        )

    def _execute_twins_simulation(self, step: int) -> List[MqttMetrics]:
        metrics_codes = self.properties.get_property(
            'boundary_condition_metrics',
            ['inflow', 'upstream_water_level'],
        )
        boundary_conditions = collect_boundary_conditions(self, step, metrics_codes)
        boundary_conditions.update(self.engine.collect_boundary_conditions(step, self))
        result = self.engine.simulate_twins_step(
            step=step,
            payload={'object_name': self.agent_name, 'object_id': 1},
            boundary_conditions=boundary_conditions,
        )
        return build_metric_messages(self, step, result.metrics)

    def on_boundary_condition_update(self, time_series_list: List[ObjectTimeSeries]) -> None:
        self.engine.handle_event(
            'boundary_condition_update',
            {'time_series': time_series_list},
            agent=self,
        )

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        shutdown_engine(self)
        return super().on_terminate(request)
"@
    }
    'OntologySimulationAgent' {
        $agentImpl = @"
from __future__ import annotations

import logging
from typing import List

from hydros_agent_sdk import $BaseClass
from hydros_agent_sdk.protocol.commands import SimTaskTerminateRequest, SimTaskTerminateResponse
from hydros_agent_sdk.utils.mqtt_metrics import MqttMetrics

from agent_app.business_engine import DemoBusinessEngine
from agent_app.support import build_metric_messages, collect_boundary_conditions, shutdown_engine

logger = logging.getLogger(__name__)


class $AgentClass($BaseClass):
    """Generated ontology-style agent scaffold with reusable lifecycle hooks."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.engine = DemoBusinessEngine()

    def _initialize_ontology_model(self) -> None:
        self.engine.initialize(
            context=self.context,
            properties=self.properties,
            topology=getattr(self, '_topology', None),
        )

    def _execute_ontology_simulation(self, step: int) -> List[MqttMetrics]:
        metrics_codes = self.properties.get_property(
            'boundary_condition_metrics',
            ['inflow', 'upstream_water_level'],
        )
        boundary_conditions = collect_boundary_conditions(self, step, metrics_codes)
        boundary_conditions.update(self.engine.collect_boundary_conditions(step, self))
        result = self.engine.run_ontology_reasoning(
            step=step,
            payload={'object_name': self.agent_name, 'object_id': 1},
            boundary_conditions=boundary_conditions,
        )
        return build_metric_messages(self, step, result.metrics)

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        shutdown_engine(self)
        return super().on_terminate(request)
"@
    }
    'CentralSchedulingAgent' {
        $agentImpl = @"
from __future__ import annotations

import logging

from hydros_agent_sdk import $BaseClass
from hydros_agent_sdk.protocol.commands import (
    OutflowTimeSeriesDataUpdateRequest,
    OutflowTimeSeriesDataUpdateResponse,
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TimeSeriesDataUpdateRequest,
    TimeSeriesDataUpdateResponse,
)

from agent_app.business_engine import DemoBusinessEngine
from agent_app.support import (
    outflow_update_response,
    register_local_agent,
    time_series_update_response,
    unregister_local_agent,
)

logger = logging.getLogger(__name__)


class $AgentClass($BaseClass):
    """Generated central scheduling style scaffold."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.engine = DemoBusinessEngine()

    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        response = register_local_agent(self, request)
        self.engine.handle_event('init', {'request': request}, agent=self)
        return response

    def on_optimization(self, step: int):
        result = self.engine.build_dispatch_plan(step=step, payload={'commands': []})
        return result.state.get('commands', [])

    def on_time_series_data_update(self, request: TimeSeriesDataUpdateRequest) -> TimeSeriesDataUpdateResponse:
        self.engine.process_time_series_update(request, agent=self)
        return time_series_update_response(self, request)

    def on_outflow_time_series_data_update(self, request: OutflowTimeSeriesDataUpdateRequest) -> OutflowTimeSeriesDataUpdateResponse:
        self.engine.process_outflow_update(request, agent=self)
        return outflow_update_response(self, request)

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        return unregister_local_agent(self, request)
"@
    }
    'ModelCalculationAgent' {
        $agentImpl = @"
from __future__ import annotations

import logging

from hydros_agent_sdk import $BaseClass
from hydros_agent_sdk.protocol.commands import SimTaskInitRequest, SimTaskInitResponse, SimTaskTerminateRequest, SimTaskTerminateResponse

from agent_app.business_engine import DemoBusinessEngine
from agent_app.support import register_local_agent, unregister_local_agent

logger = logging.getLogger(__name__)


class $AgentClass($BaseClass):
    """Generated model calculation style scaffold."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.engine = DemoBusinessEngine()

    def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
        return register_local_agent(self, request)

    def on_model_calculation(self, hydro_event):
        return self.engine.process_model_calculation(hydro_event, agent=self)

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        return unregister_local_agent(self, request)
"@
    }
    'OutflowPlanAgent' {
        $agentImpl = @"
from __future__ import annotations

import logging

from hydros_agent_sdk import $BaseClass
from hydros_agent_sdk.protocol.commands import SimTaskTerminateRequest, SimTaskTerminateResponse

from agent_app.business_engine import DemoBusinessEngine
from agent_app.support import shutdown_engine, unregister_local_agent

logger = logging.getLogger(__name__)


class $AgentClass($BaseClass):
    """Generated outflow planning style scaffold."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.engine = DemoBusinessEngine()

    def on_init(self, request):
        response = super().on_init(request)
        self.engine.initialize(
            context=self.context,
            properties=getattr(self, 'properties', None),
            topology=getattr(self, '_topology', None),
        )
        return response

    def on_outflow_time_series(self, request):
        return self.engine.process_outflow_plan(request, agent=self)

    def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
        shutdown_engine(self)
        return unregister_local_agent(self, request)
"@
    }
}

$launcher = @"
from agent_app.service import main


if __name__ == '__main__':
    main()
"@

$bootstrapScript = @"
param(
    [string]`$PythonExe = 'python'
)

`$ErrorActionPreference = 'Stop'
`$projectRoot = Split-Path -Parent `$PSScriptRoot
`$sdkRoot = '$resolvedSdkRoot'
`$venvDir = Join-Path `$projectRoot '.venv'
`$venvPython = Join-Path `$venvDir 'Scripts\python.exe'

if (-not (Test-Path `$venvDir)) {
    & `$PythonExe -m venv `$venvDir --system-site-packages
}

`$sitePackages = (& `$venvPython -c "import sysconfig; print(sysconfig.get_paths()['purelib'])").Trim()
`$pthFile = Join-Path `$sitePackages 'hydros_generated_project.pth'
[System.IO.File]::WriteAllText(`$pthFile, "`$projectRoot`n`$sdkRoot`n", (New-Object System.Text.UTF8Encoding(`$false)))

New-Item -ItemType Directory -Force -Path (Join-Path `$projectRoot 'logs') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path `$projectRoot 'data') | Out-Null

& `$venvPython -m pip install -e `$projectRoot --no-deps
& `$venvPython -c "import hydros_agent_sdk; import pathlib; print(pathlib.Path(hydros_agent_sdk.__file__).resolve())"
& `$venvPython -c "import importlib.util;mods={'paho.mqtt.client':'paho-mqtt','pydantic':'pydantic','yaml':'pyyaml'};missing=[pkg for mod,pkg in mods.items() if importlib.util.find_spec(mod) is None];print('Missing optional runtime packages: ' + ', '.join(missing) if missing else 'All runtime packages resolved.')"

Write-Host "Bootstrap finished. Source paths linked through `$pthFile. Use scripts\run.ps1 to start the agent."
"@

$runScript = @"
param(
    [string]`$PythonExe
)

`$ErrorActionPreference = 'Stop'
`$projectRoot = Split-Path -Parent `$PSScriptRoot
`$venvPython = Join-Path `$projectRoot '.venv\Scripts\python.exe'
`$launcher = Join-Path `$projectRoot 'launcher.py'

if (-not `$PythonExe) {
    if (Test-Path `$venvPython) {
        `$PythonExe = `$venvPython
    }
    else {
        `$PythonExe = 'python'
    }
}

New-Item -ItemType Directory -Force -Path (Join-Path `$projectRoot 'logs') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path `$projectRoot 'data') | Out-Null

& `$PythonExe `$launcher
"@

$gitignore = @"
.venv/
__pycache__/
*.pyc
logs/
.pytest_cache/
data/
"@

$testFile = @"
import unittest
from pathlib import Path
from types import SimpleNamespace

from hydros_agent_sdk import load_env_config, load_properties_file

from agent_app.agent_impl import $AgentClass
from agent_app.business_engine import DemoBusinessEngine, StepExecutionResult
from agent_app.runtime import discover_paths
from agent_app.user_logic import UserLogic


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONF_DIR = PROJECT_ROOT / 'conf'
ENV_FILE = CONF_DIR / 'env.properties'
AGENT_FILE = CONF_DIR / 'agent.properties'


class DummyProperties:
    def __init__(self, values):
        self.values = values

    def get_property(self, key, default=None):
        return self.values.get(key, default)


class ScaffoldImportTest(unittest.TestCase):
    def test_scaffold_files_exist(self):
        self.assertTrue(ENV_FILE.exists())
        self.assertTrue(AGENT_FILE.exists())
        self.assertTrue((PROJECT_ROOT / 'launcher.py').exists())
        self.assertTrue((PROJECT_ROOT / 'agent_app' / 'agent_impl.py').exists())
        self.assertTrue((PROJECT_ROOT / 'agent_app' / 'runtime.py').exists())
        self.assertTrue((PROJECT_ROOT / 'agent_app' / 'support.py').exists())
        self.assertTrue((PROJECT_ROOT / 'agent_app' / 'user_logic.py').exists())

    def test_generated_configs_can_be_loaded(self):
        env_config = load_env_config(str(ENV_FILE.resolve()))
        agent_config = load_properties_file(str(AGENT_FILE.resolve()))

        self.assertEqual(env_config['hydros_cluster_id'], 'default_cluster')
        self.assertEqual(env_config['mqtt_topic'], '/hydros/commands/coordination/default_cluster')
        self.assertEqual(agent_config['agent_code'], '$AgentCode')
        self.assertEqual(agent_config['agent_name'], '$AgentClass')
        if agent_config['agent_type'] == 'TWINS_SIMULATION_AGENT':
            self.assertIn('idz_config_url', agent_config)
            self.assertIn('corelib_package_root', agent_config)
            self.assertEqual(agent_config['solver_backend'], 'dry_run')

    def test_runtime_modules_import(self):
        paths = discover_paths()
        self.assertEqual(paths.project_root, PROJECT_ROOT)
        self.assertTrue(issubclass($AgentClass, object))
        self.assertIsInstance(DemoBusinessEngine(), DemoBusinessEngine)
        self.assertIsInstance(UserLogic(), UserLogic)

    def test_twins_user_logic_dry_run(self):
        logic = UserLogic()
        context = SimpleNamespace(biz_scene_instance_id='TEST_JOB')
        properties = DummyProperties(
            {
                'time_step': 60,
                'convergence_tolerance': 1e-6,
                'max_iterations': 100,
                'solver_backend': 'dry_run',
                'solver_mode': 'hydraulic',
                'corelib_package_root': 'C:/replace-with-corelib-parent',
                'idz_local_cache_dir': 'data',
                'idz_config_url': 'https://replace-with-idz-config.example.com/idz.yml',
            }
        )
        logic.initialize(context=context, properties=properties, topology=None)
        result = logic.simulate_twins_step(
            step=3,
            payload={'object_name': 'GeneratedObject'},
            boundary_conditions={10: {'upstream_water_level': 2.5, 'inflow': 8.0}},
        )
        self.assertIsInstance(result, StepExecutionResult)
        self.assertEqual(result.state['solver_backend'], 'dry_run')
        self.assertGreaterEqual(len(result.metrics), 2)
        logic.shutdown()


if __name__ == '__main__':
    unittest.main()
"@

Write-Utf8File -Path (Join-Path $projectRoot 'pyproject.toml') -Content $pyproject
Write-Utf8File -Path (Join-Path $projectRoot 'README.md') -Content $readme
Write-Utf8File -Path (Join-Path $projectRoot '.gitignore') -Content $gitignore
Write-Utf8File -Path (Join-Path $projectRoot 'launcher.py') -Content $launcher
Write-Utf8File -Path (Join-Path $confDir 'env.properties') -Content $envProps
Write-Utf8File -Path (Join-Path $confDir 'agent.properties') -Content $agentProps
Write-Utf8File -Path (Join-Path $agentAppDir '__init__.py') -Content $initPy
Write-Utf8File -Path (Join-Path $agentAppDir 'business_engine.py') -Content $businessEngine
Write-Utf8File -Path (Join-Path $agentAppDir 'user_logic.py') -Content $userLogicModule
Write-Utf8File -Path (Join-Path $agentAppDir 'support.py') -Content $supportModule
Write-Utf8File -Path (Join-Path $agentAppDir 'runtime.py') -Content $runtimeModule
Write-Utf8File -Path (Join-Path $agentAppDir 'service.py') -Content $serviceModule
Write-Utf8File -Path (Join-Path $agentAppDir 'agent_impl.py') -Content $agentImpl
if ($ScaffoldTemplate -eq 'twins') {
    Write-Utf8File -Path (Join-Path $agentAppDir 'hydraulic_solver.py') -Content $twinsHydraulicSolverModule
    Write-Utf8File -Path (Join-Path $agentAppDir 'simulation_states.py') -Content $twinsSimulationStatesModule
}
Write-Utf8File -Path (Join-Path $projectScriptsDir 'bootstrap.ps1') -Content $bootstrapScript
Write-Utf8File -Path (Join-Path $projectScriptsDir 'run.ps1') -Content $runScript
Write-Utf8File -Path (Join-Path $testsDir '__init__.py') -Content '# Generated test package'
Write-Utf8File -Path (Join-Path $testsDir 'test_scaffold_import.py') -Content $testFile

$summary = @"
Hydros agent scaffold generated successfully.

Project Root : $projectRoot
SDK Root     : $resolvedSdkRoot
Agent Class  : $AgentClass
Agent Code   : $AgentCode
Agent Type   : $AgentType
Base Class   : $BaseClass

Next steps:
1. powershell -ExecutionPolicy Bypass -File .\\scripts\\bootstrap.ps1
2. Edit conf\\env.properties and conf\\agent.properties
3. Implement domain logic in agent_app\\user_logic.py
4. powershell -ExecutionPolicy Bypass -File .\\scripts\\run.ps1
5. .\\.venv\\Scripts\\python.exe -m unittest tests.test_scaffold_import
"@

Write-Host $summary
