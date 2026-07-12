import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class DataColumn:
    key: str
    label: str


class DevicePlugin(ABC):
    device_id: str
    display_name: str
    order: int = 100
    connection_label: str = "Address"
    default_connection: str = ""
    columns: tuple[DataColumn, ...] = ()
    settings_factory: Callable[[Any, Any], Any] | None = None

    @abstractmethod
    def connect(self, connection: str):
        """Create and return a connected device driver."""

    def format_connected(self, connection: str) -> str:
        return f"{self.display_name} connected: {connection}"

    def format_disconnected(self) -> str:
        return f"{self.display_name} disconnected"


def load_device_plugins() -> dict[str, DevicePlugin]:
    """Discover ``plugins.devices.<name>.plugin`` packages."""
    package = importlib.import_module("plugins.devices")
    plugins: dict[str, DevicePlugin] = {}
    for info in pkgutil.iter_modules(package.__path__):
        if not info.ispkg or info.name.startswith("_"):
            continue
        module = importlib.import_module(f"plugins.devices.{info.name}.plugin")
        candidate = getattr(module, "plugin", None)
        if not isinstance(candidate, DevicePlugin):
            continue
        if candidate.device_id in plugins:
            raise ValueError(f"Duplicate device plug-in id: {candidate.device_id}")
        plugins[candidate.device_id] = candidate
    return dict(sorted(plugins.items(), key=lambda item: (item[1].order, item[0])))
