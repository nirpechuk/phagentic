from abc import ABC, abstractmethod
from typing import Optional


class Transport(ABC):
    """Swap this out for WebSocket, MQTT, etc. — Controller only talks to this."""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def send(self, message: dict) -> None: ...

    @abstractmethod
    def receive(self, timeout: float = 1.0) -> Optional[dict]: ...

    @abstractmethod
    def is_connected(self) -> bool: ...
