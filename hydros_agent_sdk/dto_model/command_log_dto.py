"""
向后兼容的 DTO 导入。

新代码应从 hydros_agent_sdk.agent_commands.models 导入 CommandLogDTO。
"""

from hydros_agent_sdk.agent_commands.models import CommandLogDTO

__all__ = ["CommandLogDTO"]
