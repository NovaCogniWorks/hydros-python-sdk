"""
未上报智能体命令日志的周期性上报调度器。
"""

from __future__ import annotations

import logging
import time
from threading import Event, Thread
from typing import Callable, Optional, Sequence

from hydros_agent_sdk.agent_commands.persistence import AgentCommandLogEntry
from hydros_agent_sdk.agent_commands.models import CommandLogDTO
from hydros_agent_sdk.protocol.system_commands import HydroCommandLogReportRequest

logger = logging.getLogger(__name__)


class HydroCommandLogReportScheduler:
    """定期收集未上报命令日志并提交批量上报请求。"""

    INTERVAL_COUNT = 10

    def __init__(
        self,
        runtime,
        submit_command: Callable[[HydroCommandLogReportRequest], None],
        interval_seconds: float = 10.0,
        report_limit: int = 100,
    ):
        self.runtime = runtime
        self.submit_command = submit_command
        self.interval_seconds = float(interval_seconds)
        self.report_limit = report_limit

        self._running = Event()
        self._thread: Optional[Thread] = None

    def start(self) -> None:
        """启动后台上报。"""
        if self._running.is_set():
            return

        self._running.set()
        self._thread = Thread(target=self._run_loop, daemon=True, name="HydroCommandLogReportScheduler")
        self._thread.start()

    def stop(self) -> None:
        """停止后台上报。"""
        if not self._running.is_set():
            return

        self._running.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(self.interval_seconds, 1.0) + 1.0)
        self._thread = None

    def do_sync(self) -> Optional[HydroCommandLogReportRequest]:
        """执行一次上报周期。"""
        command_log_entries = self.runtime.find_unreported_command_logs(limit=self.report_limit)
        if not command_log_entries:
            return None

        command_log_report_request = self.build_request(command_log_entries)
        self.submit_command(command_log_report_request)
        self.runtime.log_ops.mark_reported(command_log_entries)

        logger.warning(
            "HydroCommandLogReportScheduler started,%s CommandLogs waiting to sync",
            len(command_log_entries),
        )
        return command_log_report_request

    def build_request(self, command_log_entries: Sequence[AgentCommandLogEntry]) -> HydroCommandLogReportRequest:
        """根据命令日志构建批量上报请求。"""
        current_node_id = self.runtime.state_manager.get_node_id() or "UNKNOWN"
        return HydroCommandLogReportRequest(
            need_ack_reply=False,
            source_id=current_node_id,
            target_id="default_data",
            agent_logs=[CommandLogDTO.model_validate(entry, from_attributes=True) for entry in command_log_entries],
        )

    def _run_loop(self) -> None:
        while self._running.is_set():
            try:
                self.do_sync()
            except Exception as exc:
                logger.error("HydroCommandLogReportScheduler failed: %s", exc, exc_info=True)

            if not self._running.is_set():
                break
            time.sleep(max(self.interval_seconds, 0.0))
