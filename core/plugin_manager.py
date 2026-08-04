import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class DataColumn:
    key: str
    label: str


@dataclass(frozen=True)
class ExperimentPlugin:
    experiment_id: str
    display_name: str
    recipe_factory: Callable[[], list[dict[str, Any]]] | None = None
    panel_factory: Callable[[Any, Any], Any] | None = None
    description: str = ""
    order: int = 100

    def create_recipe(self) -> list[dict[str, Any]]:
        """Return a fresh sequence recipe for this experiment."""
        if self.recipe_factory is None:
            raise ValueError(f"{self.display_name} does not provide a sequence recipe.")
        return [dict(step) for step in self.recipe_factory()]


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


def load_experiment_plugins() -> dict[str, ExperimentPlugin]:
    """Discover modules exporting ``plugin`` from ``plugins.experiments``."""
    package = importlib.import_module("plugins.experiments")
    plugins: dict[str, ExperimentPlugin] = {}
    for info in pkgutil.iter_modules(package.__path__):
        if info.ispkg or info.name.startswith("_"):
            continue
        module = importlib.import_module(f"plugins.experiments.{info.name}")
        candidate = getattr(module, "plugin", None)
        if not isinstance(candidate, ExperimentPlugin):
            continue
        if candidate.experiment_id in plugins:
            raise ValueError(f"Duplicate experiment plug-in id: {candidate.experiment_id}")
        plugins[candidate.experiment_id] = candidate
    return dict(sorted(plugins.items(), key=lambda item: (item[1].order, item[0])))
