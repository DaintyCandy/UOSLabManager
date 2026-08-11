import importlib
import importlib.util
import json
import os
import pkgutil
import re
import shutil
import sys
import tempfile
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Callable


@dataclass(frozen=True)
class DataColumn:
    key: str
    label: str


@dataclass(frozen=True)
class SequenceCommand:
    key: str
    label: str
    unit: str = ""
    minimum: float = -1_000_000.0
    maximum: float = 1_000_000.0
    default: float = 0.0
    decimals: int = 2
    requires_value: bool = True


@dataclass(frozen=True)
class ExperimentPlugin:
    experiment_id: str
    display_name: str
    recipe_factory: Callable[[], list[dict[str, Any]]] | None = None
    panel_factory: Callable[[Any, Any], Any] | None = None
    sequence_commands: tuple[SequenceCommand, ...] = ()
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


def load_device_plugins(*, reload_modules: bool = False) -> dict[str, DevicePlugin]:
    """Discover ``plugins.devices.<name>.plugin`` packages."""
    package = importlib.import_module("plugins.devices")
    plugins: dict[str, DevicePlugin] = {}
    for info in pkgutil.iter_modules(package.__path__):
        if not info.ispkg or info.name.startswith("_"):
            continue
        module_name = f"plugins.devices.{info.name}.plugin"
        if reload_modules:
            package_prefix = f"plugins.devices.{info.name}"
            for loaded_name in tuple(sys.modules):
                if loaded_name == package_prefix or loaded_name.startswith(
                    package_prefix + "."
                ):
                    sys.modules.pop(loaded_name, None)
        module = importlib.import_module(module_name)
        candidate = getattr(module, "plugin", None)
        if not isinstance(candidate, DevicePlugin):
            continue
        if candidate.device_id in plugins:
            raise ValueError(f"Duplicate device plug-in id: {candidate.device_id}")
        plugins[candidate.device_id] = candidate
    return dict(sorted(plugins.items(), key=lambda item: (item[1].order, item[0])))


def get_plugin_root() -> Path:
    """Return the unified editable plug-in root used by Plugin Studio.

    ``UOSLAB_PLUGIN_DIR`` makes the location configurable for packaged
    applications while keeping a repository-local default during development.
    The former ``UOSLAB_USER_PLUGIN_DIR`` name remains supported.
    """
    configured = os.environ.get("UOSLAB_PLUGIN_DIR") or os.environ.get(
        "UOSLAB_USER_PLUGIN_DIR"
    )
    if configured:
        return Path(configured).expanduser().resolve()

    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        data_root = (
            Path(local_app_data)
            if local_app_data
            else Path.home() / "AppData" / "Local"
        )
        destination = data_root / "UOSLabManager" / "plugins"
        legacy_root = data_root / "UOSLabManager" / "user_plugins"
        bundled_root = Path(getattr(sys, "_MEIPASS", "")) / "plugins"
        _seed_plugins(legacy_root, destination)
        _seed_plugins(bundled_root, destination)
        return destination.resolve()

    return Path(__file__).resolve().parents[1] / "plugins"


def get_user_plugin_root() -> Path:
    """Backward-compatible alias for the unified plug-in root."""
    return get_plugin_root()


def _plugin_manifest(plugin_dir: Path) -> dict[str, Any]:
    manifest_path = plugin_dir / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plugin_id = manifest.get("id")
    if manifest.get("type") != "experiment":
        raise ValueError("Only experiment plugins can be imported or exported")
    if not isinstance(plugin_id, str) or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_]*", plugin_id
    ):
        raise ValueError("Plugin manifest contains an invalid id")
    entrypoint = manifest.get("entrypoint", "plugin.py:plugin")
    module_file, separator, attribute = entrypoint.partition(":")
    if not separator or not module_file or not attribute:
        raise ValueError("Plugin entrypoint must look like plugin.py:plugin")
    source_path = (plugin_dir / module_file).resolve()
    if source_path.parent != plugin_dir.resolve() or not source_path.is_file():
        raise ValueError(f"Plugin entrypoint does not exist: {module_file}")
    return manifest


def export_experiment_plugin(plugin_dir: Path, archive_path: Path) -> Path:
    """Export an editable experiment plugin as a portable .uosplugin archive."""
    plugin_dir = Path(plugin_dir).resolve()
    _plugin_manifest(plugin_dir)
    archive_path = Path(archive_path)
    if archive_path.suffix.lower() != ".uosplugin":
        archive_path = archive_path.with_suffix(".uosplugin")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for source_path in sorted(plugin_dir.rglob("*")):
            if (
                not source_path.is_file()
                or "__pycache__" in source_path.parts
                or source_path.suffix in {".pyc", ".pyo"}
            ):
                continue
            archive.write(source_path, source_path.relative_to(plugin_dir).as_posix())
    return archive_path


def import_experiment_plugin(
    archive_path: Path, plugin_root: Path, *, replace: bool = False
) -> Path:
    """Validate and install a .uosplugin archive into ``plugin_root``."""
    archive_path = Path(archive_path)
    plugin_root = Path(plugin_root).resolve()
    plugin_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=plugin_root) as temporary_directory:
        temporary = Path(temporary_directory)
        with zipfile.ZipFile(archive_path, "r") as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            if not files or len(files) > 250:
                raise ValueError("Plugin archive is empty or contains too many files")
            if sum(item.file_size for item in files) > 25 * 1024 * 1024:
                raise ValueError("Plugin archive expands beyond the 25 MB limit")
            for item in files:
                relative = PurePosixPath(item.filename)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not relative.parts
                ):
                    raise ValueError(f"Unsafe path in plugin archive: {item.filename}")
                target = temporary.joinpath(*relative.parts).resolve()
                if temporary.resolve() not in target.parents:
                    raise ValueError(f"Unsafe path in plugin archive: {item.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)

        candidates = [temporary]
        top_level_dirs = [path for path in temporary.iterdir() if path.is_dir()]
        top_level_files = [path for path in temporary.iterdir() if path.is_file()]
        if not top_level_files and len(top_level_dirs) == 1:
            candidates.insert(0, top_level_dirs[0])
        source_dir = next(
            (path for path in candidates if (path / "plugin.json").is_file()), None
        )
        if source_dir is None:
            raise ValueError("Plugin archive does not contain plugin.json")
        manifest = _plugin_manifest(source_dir)
        destination = plugin_root / manifest["id"]
        if destination.exists() and not replace:
            raise FileExistsError(str(destination))

        staged = plugin_root / f".__import_{manifest['id']}__"
        backup = plugin_root / f".__backup_{manifest['id']}__"
        if staged.exists() or backup.exists():
            raise OSError("A previous plugin import did not finish cleanly")
        shutil.copytree(source_dir, staged)
        try:
            if destination.exists():
                destination.rename(backup)
            staged.rename(destination)
        except Exception:
            if backup.exists() and not destination.exists():
                backup.rename(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return destination


def _seed_plugins(source: Path, destination: Path) -> None:
    """Copy packaged defaults without overwriting user-created or edited files."""
    destination.mkdir(parents=True, exist_ok=True)
    if not source.is_dir():
        return
    for source_path in source.rglob("*"):
        relative = source_path.relative_to(source)
        target = destination / relative
        if source_path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)


def _load_user_experiment_plugin(manifest_path: Path) -> ExperimentPlugin | None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("type") != "experiment" or not manifest.get("enabled", True):
        return None
    manifest_id = manifest.get("id")
    if not isinstance(manifest_id, str) or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_]*", manifest_id
    ):
        raise ValueError(f"Invalid experiment plug-in id in {manifest_path}")
    entrypoint = manifest.get("entrypoint", "plugin.py:plugin")
    module_file, separator, attribute = entrypoint.partition(":")
    if not separator or not module_file or not attribute:
        raise ValueError(f"Invalid entrypoint in {manifest_path}: {entrypoint}")
    source_path = (manifest_path.parent / module_file).resolve()
    if source_path.parent != manifest_path.parent.resolve() or not source_path.is_file():
        raise ValueError(f"Invalid plug-in source path: {source_path}")

    module_name = f"_uoslab_user_experiment_{manifest_id}"
    for loaded_name in tuple(sys.modules):
        if loaded_name == module_name or loaded_name.startswith(module_name + "."):
            sys.modules.pop(loaded_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        source_path,
        submodule_search_locations=[str(manifest_path.parent)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load experiment plug-in: {source_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    candidate = getattr(module, attribute, None)
    if not isinstance(candidate, ExperimentPlugin):
        raise TypeError(f"{entrypoint} does not export an ExperimentPlugin")
    if candidate.experiment_id != manifest_id:
        raise ValueError(
            f"Manifest id {manifest_id!r} does not match "
            f"ExperimentPlugin id {candidate.experiment_id!r}"
        )
    return candidate


def _load_user_experiment_plugins(
    root: Path, strict: bool = True,
) -> dict[str, ExperimentPlugin]:
    plugins: dict[str, ExperimentPlugin] = {}
    if not root.is_dir():
        return plugins

    for manifest_path in sorted(root.glob("*/plugin.json")):
        try:
            candidate = _load_user_experiment_plugin(manifest_path)
        except Exception:
            if strict:
                raise
            continue
        if candidate is not None:
            plugins[candidate.experiment_id] = candidate
    return plugins


def load_experiment_plugins(
    user_plugin_root: str | os.PathLike[str] | None = None,
    *,
    strict: bool = True,
) -> dict[str, ExperimentPlugin]:
    """Discover built-in and editable user experiment plug-ins."""
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
    user_root = (
        Path(user_plugin_root)
        if user_plugin_root is not None
        else get_plugin_root()
    ) / "experiments"
    for experiment_id, candidate in _load_user_experiment_plugins(
        user_root, strict=strict
    ).items():
        if experiment_id in plugins:
            raise ValueError(f"Duplicate experiment plug-in id: {experiment_id}")
        plugins[experiment_id] = candidate
    return dict(sorted(plugins.items(), key=lambda item: (item[1].order, item[0])))
