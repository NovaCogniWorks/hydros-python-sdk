"""Command routing helpers for SimCoordinationClient."""

import logging
from typing import Callable, Dict

logger = logging.getLogger(__name__)


class CommandRouter:
    """Routes commands to registered handlers."""

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}

    @property
    def handlers(self) -> Dict[str, Callable]:
        return dict(self._handlers)

    def register(self, command_type: str, handler: Callable) -> None:
        self._handlers[command_type] = handler

    def register_many(self, handlers: Dict[str, Callable]) -> None:
        self._handlers.update(handlers)

    def route(self, command) -> None:
        handler = self._handlers.get(command.command_type)
        if handler is None:
            logger.warning(f"No handler registered for command type: {command.command_type}")
            return

        logger.debug(f"Handling command: {command.command_type}, id={command.command_id}")
        handler(command)
