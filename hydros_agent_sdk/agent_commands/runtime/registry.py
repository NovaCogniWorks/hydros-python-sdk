"""
智能体指令处理器注册表。
"""

from __future__ import annotations

from typing import Dict

from .handlers import AgentCommandHandler


class AgentCommandHandlerRegistry:
    """先走显式注册，别在 Python 里硬模仿 Spring 扫描。"""

    def __init__(self):
        self._handlers: Dict[str, AgentCommandHandler] = {}

    def register_handler(self, handler: AgentCommandHandler) -> None:
        command = handler.get_command()
        if command in self._handlers:
            raise ValueError(f"command_type '{command}' 已经注册过了")
        self._handlers[command] = handler

    def get_handler(self, command_type: str) -> AgentCommandHandler:
        handler = self._handlers.get(command_type)
        if handler is None:
            raise KeyError(f"没有找到 command_type='{command_type}' 的 handler")
        return handler

    def has_handler(self, command_type: str) -> bool:
        return command_type in self._handlers

    def list_commands(self) -> list[str]:
        return sorted(self._handlers.keys())
