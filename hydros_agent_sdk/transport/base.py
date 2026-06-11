"""
协调消息投递的传输接口。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


MessageHandler = Callable[[str, str], None]


@dataclass(frozen=True)
class PublishRecord:
    """通过传输层发布的一条消息。"""

    topic: str
    payload: str
    qos: int = 1


class Transport(Protocol):
    """发布/订阅消息风格的最小传输协议。"""

    def start(self) -> None:
        """启动传输资源。"""
        ...

    def stop(self) -> None:
        """停止传输资源。"""
        ...

    def subscribe(self, topic: str, handler: MessageHandler, qos: int = 1) -> None:
        """把处理器订阅到指定 topic。"""
        ...

    def publish(self, topic: str, payload: str, qos: int = 1) -> None:
        """向指定 topic 发布 payload。"""
        ...
