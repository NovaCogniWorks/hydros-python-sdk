"""Core package for the ODD-driven hierarchical DMPC prototype."""

import os
from pathlib import Path

MPL_DIR = Path(__file__).resolve().parents[1] / "output" / ".matplotlib"
MPL_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPL_DIR))

from .config import load_runtime_context, load_runtime_parameters
from .environment import RemoteHydraulicEnvironment
from .flow_service import FlowDepartService
from .observers import DisturbanceObserverBank
from .odd_supervisor import ODDSupervisor
from .simulation import ClosedLoopSimulation
from .station_model import PumpStationModel
from .thread_client import RemoteThreadClient
from .thread_snapshot import parse_thread_snapshot
from .upper_scheduler import UpperScheduler

__all__ = [
    "ClosedLoopSimulation",
    "DisturbanceObserverBank",
    "FlowDepartService",
    "ODDSupervisor",
    "PumpStationModel",
    "RemoteHydraulicEnvironment",
    "RemoteThreadClient",
    "UpperScheduler",
    "load_runtime_context",
    "load_runtime_parameters",
    "parse_thread_snapshot",
]
