"""
Backward-compatible DTO imports.

New code should import CommandLogDTO from hydros_agent_sdk.agent_commands.models.
"""

from hydros_agent_sdk.agent_commands.models import CommandLogDTO

__all__ = ["CommandLogDTO"]
