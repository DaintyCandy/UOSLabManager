import importlib
import importlib.util
import json
import keyword
import math
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


PLUGIN_ID_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL", "CLOCK$",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class DataColumn:
    key: str
    label: str
    unit: str = ""
    condition_label: str = ""

    @property
    def wait_condition_enabled(self) -> bool:
        """Return whether the column can be selected by a sequence condition."""
        return bool(self.condition_label)


@dataclass(frozen=True)
class AlarmRule:
    """Describe a measurement value that should be reported on state changes."""

    key: str
    message: str = "{device} alarm: {value}"
    normal_values: tuple[Any, ...] = (None, "", False, 0)

    def is_active(self, value: Any) -> bool:
        return not any(value == normal for normal in self.normal_values)

    def format_message(self, device: str, value: Any) -> str:
        return self.message.format(device=device, value=value)


@dataclass(frozen=True)
class SafeAction:
    """One best-effort driver call used to put a device in a safe state."""

    method: str
    args: tuple[Any, ...] = ()
    kwargs: tuple[tuple[str, Any], ...] = ()

    def execute(self, device: Any) -> Any:
        return getattr(device, self.method)(*self.args, **dict(self.kwargs))


@dataclass(frozen=True)
class RecipeMigration:
    """Translate one legacy plug-in command into a current recipe step."""

    command: str
    target_device: str
    target_command: str
    transform: Callable[[Any], Any] = lambda value: value

    def apply(self, value: Any) -> dict[str, Any]:
        return {
            "dev": self.target_device,
            "cmd": self.target_command,
            "val": self.transform(value),
        }


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
    choices: tuple[str, ...] = ()
    settle_seconds: float = 0.0
    executor: Callable[[Any, Any, Any], Any] | None = None

    def validate(self, value: Any) -> Any:
        """Validate and normalize a recipe value using plug-in metadata."""
        if not self.requires_value:
            return 0
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{self.label} value must be numeric")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{self.label} value must be finite")
        if not self.minimum <= numeric <= self.maximum:
            raise ValueError(
                f"{self.label} value must be between {self.minimum:g} "
                f"and {self.maximum:g} {self.unit}".rstrip()
            )
        if self.choices:
            choice = int(numeric)
            if numeric != choice or not 0 <= choice < len(self.choices):
                raise ValueError(f"{self.label} contains an invalid choice")
            return choice
        return numeric

    def execute(self, device: Any, value: Any, context: Any) -> Any:
        """Run a declared device command without GUI-side dispatch logic."""
        if self.executor is None:
            raise RuntimeError(f"{self.label} has no device executor")
        return self.executor(device, self.validate(value), context)

    def format_value(self, value: Any) -> str:
        if not self.requires_value:
            return ""
        normalized = self.validate(value)
        if self.choices:
            return self.choices[normalized]
        suffix = f" {self.unit}" if self.unit else ""
        return f"{normalized:g}{suffix}"


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
    profile: str = "standard"
    version: str = "0.1.0"
    order: int = 100
    connection_label: str = "Address"
    default_connection: str = ""
    columns: tuple[DataColumn, ...] = ()
    alarms: tuple[AlarmRule, ...] = ()
    safe_actions: tuple[SafeAction, ...] = ()
    settings_factory: Callable[[Any, Any], Any] | None = None
    sequence_commands: tuple[SequenceCommand, ...] = ()
    sequence_aliases: tuple[str, ...] = ()
    recipe_migrations: tuple[RecipeMigration, ...] = ()

    @abstractmethod
    def connect(self, connection: str):
        """Create and return a connected device driver."""

    def format_connected(self, connection: str) -> str:
        return f"{self.display_name} connected: {connection}"

    def format_disconnected(self) -> str:
        return f"{self.display_name} disconnected"

    def get_sequence_command(self, key: str) -> SequenceCommand | None:
        return next(
            (command for command in self.sequence_commands if command.key == key),
            None,
        )

    def get_recipe_migration(self, key: str) -> RecipeMigration | None:
        return next(
            (
                migration
                for migration in self.recipe_migrations
                if migration.command == key
            ),
            None,
        )

    def enter_safe_state(self, device: Any) -> None:
        """Run every declared safe-state action and report all failures together."""
        errors = []
        for action in self.safe_actions:
            try:
                action.execute(device)
            except Exception as error:
                errors.append(f"{action.method}: {error}")
        if errors:
            raise RuntimeError("; ".join(errors))


def load_device_plugins(
    device_plugin_root: str | os.PathLike[str] | None = None,
    *,
    reload_modules: bool = False,
    strict: bool = True,
) -> dict[str, DevicePlugin]:
    """Discover editable, manifest-based device plug-ins."""
    root = (
        Path(device_plugin_root)
        if device_plugin_root is not None
        else get_plugin_root() / "devices"
    )
    plugins: dict[str, DevicePlugin] = {}
    normalized_ids: set[str] = set()
    if not root.is_dir():
        return plugins
    for manifest_path in sorted(root.glob("*/plugin.json")):
        try:
            candidate = _load_device_plugin(
                manifest_path, reload_modules=reload_modules
            )
        except Exception:
            if strict:
                raise
            continue
        if candidate is None:
            continue
        normalized_id = candidate.device_id.casefold()
        if normalized_id in normalized_ids:
            if strict:
                raise ValueError(
                    f"Duplicate device plug-in id: {candidate.device_id}"
                )
            continue
        normalized_ids.add(normalized_id)
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
        _migrate_legacy_bundled_plugins(bundled_root, destination)
        return destination.resolve()

    return Path(__file__).resolve().parents[1] / "plugins"


def get_user_plugin_root() -> Path:
    """Backward-compatible alias for the unified plug-in root."""
    return get_plugin_root()


def validate_plugin_id(plugin_id: str) -> str:
    """Validate one portable identifier shared by every plug-in type."""
    if not isinstance(plugin_id, str):
        raise ValueError("Plugin ID must be text")
    if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
        raise ValueError(
            "Plugin ID must be 1-64 ASCII characters, start with a letter, "
            "and contain only letters, numbers, or underscores"
        )
    if keyword.iskeyword(plugin_id):
        raise ValueError("Plugin ID cannot be a Python keyword")
    if plugin_id.upper() in WINDOWS_RESERVED_NAMES:
        raise ValueError("Plugin ID is a reserved Windows file name")
    return plugin_id


def resolve_plugin_python_path(plugin_dir: Path, relative_path: str) -> Path:
    """Resolve one importable .py path without allowing package traversal."""
    plugin_dir = Path(plugin_dir).resolve()
    normalized = str(relative_path).strip().replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        not normalized
        or relative.is_absolute()
        or ".." in relative.parts
        or relative.suffix != ".py"
    ):
        raise ValueError("Use a relative .py path inside the plugin")
    for index, part in enumerate(relative.parts):
        name = part[:-3] if index == len(relative.parts) - 1 else part
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError("Python file and package names must be valid identifiers")
    target = plugin_dir.joinpath(*relative.parts).resolve()
    if plugin_dir not in target.parents:
        raise ValueError("The Python file path is outside the plugin")
    return target


def _plugin_manifest(
    plugin_dir: Path, expected_type: str | None = None
) -> dict[str, Any]:
    manifest_path = plugin_dir / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plugin_id = manifest.get("id")
    plugin_type = manifest.get("type")
    if plugin_type not in {"experiment", "device"}:
        raise ValueError("Plugin type must be 'experiment' or 'device'")
    if expected_type is not None and plugin_type != expected_type:
        raise ValueError(f"Expected a {expected_type} plugin")
    if plugin_type == "device" and manifest.get("profile", "standard") not in {
        "standard", "composite",
    }:
        raise ValueError("Device profile must be 'standard' or 'composite'")
    validate_plugin_id(plugin_id)
    entrypoint = manifest.get("entrypoint", "plugin.py:plugin")
    module_file, separator, attribute = entrypoint.partition(":")
    if not separator or not module_file or not attribute:
        raise ValueError("Plugin entrypoint must look like plugin.py:plugin")
    source_path = (plugin_dir / module_file).resolve()
    if source_path.parent != plugin_dir.resolve() or not source_path.is_file():
        raise ValueError(f"Plugin entrypoint does not exist: {module_file}")
    return manifest


def export_plugin(plugin_dir: Path, archive_path: Path) -> Path:
    """Export an experiment or device package as a portable archive."""
    return _export_plugin(plugin_dir, archive_path)


def export_experiment_plugin(plugin_dir: Path, archive_path: Path) -> Path:
    """Export an editable experiment plugin as a portable .uosplugin archive."""
    return _export_plugin(plugin_dir, archive_path, expected_type="experiment")


def export_device_plugin(plugin_dir: Path, archive_path: Path) -> Path:
    """Export an editable device plugin as a portable .uosplugin archive."""
    return _export_plugin(plugin_dir, archive_path, expected_type="device")


def _export_plugin(
    plugin_dir: Path, archive_path: Path, expected_type: str | None = None
) -> Path:
    plugin_dir = Path(plugin_dir).resolve()
    _plugin_manifest(plugin_dir, expected_type)
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


def import_plugin(
    archive_path: Path, plugin_root: Path, *, replace: bool = False
) -> Path:
    """Install an archive into the matching devices/experiments directory."""
    return _import_plugin_archive(
        archive_path, plugin_root, replace=replace, categorize=True
    )


def import_experiment_plugin(
    archive_path: Path, plugin_root: Path, *, replace: bool = False
) -> Path:
    """Validate and install an experiment archive into ``plugin_root``."""
    return _import_plugin_archive(
        archive_path, plugin_root, replace=replace, expected_type="experiment"
    )


def import_device_plugin(
    archive_path: Path, plugin_root: Path, *, replace: bool = False
) -> Path:
    """Validate and install a device archive into ``plugin_root``."""
    return _import_plugin_archive(
        archive_path, plugin_root, replace=replace, expected_type="device"
    )


def _import_plugin_archive(
    archive_path: Path,
    plugin_root: Path,
    *,
    replace: bool = False,
    expected_type: str | None = None,
    categorize: bool = False,
) -> Path:
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
        manifest = _plugin_manifest(source_dir, expected_type)
        destination_root = plugin_root
        if categorize:
            category = "devices" if manifest["type"] == "device" else "experiments"
            destination_root = plugin_root / category
            destination_root.mkdir(parents=True, exist_ok=True)
        destination = destination_root / manifest["id"]
        existing_destination = None
        for existing_manifest in destination_root.glob("*/plugin.json"):
            existing_parent = existing_manifest.parent.resolve()
            temporary_root = temporary.resolve()
            if (
                existing_parent == temporary_root
                or temporary_root in existing_parent.parents
            ):
                continue
            try:
                existing_id = json.loads(
                    existing_manifest.read_text(encoding="utf-8")
                ).get("id")
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if (
                isinstance(existing_id, str)
                and existing_id.casefold() == manifest["id"].casefold()
            ):
                existing_destination = existing_parent
                break
        if existing_destination is None and destination.exists():
            existing_destination = destination
        if existing_destination is not None and not replace:
            raise FileExistsError(str(existing_destination))

        staged = destination_root / f".__import_{manifest['id']}__"
        backup = destination_root / f".__backup_{manifest['id']}__"
        if staged.exists() or backup.exists():
            raise OSError("A previous plugin import did not finish cleanly")
        shutil.copytree(source_dir, staged)
        try:
            if existing_destination is not None:
                existing_destination.rename(backup)
            staged.rename(destination)
        except Exception:
            if backup.exists() and not destination.exists():
                backup.rename(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return destination


def _load_device_plugin(
    manifest_path: Path, *, reload_modules: bool = False
) -> DevicePlugin | None:
    manifest = _plugin_manifest(manifest_path.parent, expected_type="device")
    if not manifest.get("enabled", True):
        return None
    plugin_id = manifest["id"]
    entrypoint = manifest.get("entrypoint", "plugin.py:plugin")
    module_file, _, attribute = entrypoint.partition(":")
    source_path = manifest_path.parent / module_file
    module_name = f"_uoslab_device_{plugin_id}"
    if reload_modules or module_name in sys.modules:
        for loaded_name in tuple(sys.modules):
            if loaded_name == module_name or loaded_name.startswith(module_name + "."):
                sys.modules.pop(loaded_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        source_path,
        submodule_search_locations=[str(manifest_path.parent)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load device plug-in: {source_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    candidate = getattr(module, attribute, None)
    if not isinstance(candidate, DevicePlugin):
        raise TypeError(f"{entrypoint} does not export a DevicePlugin")
    if candidate.device_id != plugin_id:
        raise ValueError(
            f"Manifest id {plugin_id!r} does not match "
            f"DevicePlugin id {candidate.device_id!r}"
        )
    candidate.profile = manifest.get("profile", "standard")
    candidate.version = str(manifest.get("version", "0.1.0"))
    return candidate


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


def _migrate_legacy_bundled_plugins(source: Path, destination: Path) -> None:
    """Replace known incompatible bundled defaults while preserving a backup."""
    migrations = (
        (
            Path("devices/ctvideo_3m/panel.py"),
            "from gui.panel_ctvideo import CTVideoView",
        ),
        (
            Path("experiments/heating_control/panel.py"),
            "from gui.panel_ctvideo import CTVideoView",
        ),
    )
    for relative, obsolete_marker in migrations:
        source_path = source / relative
        target = destination / relative
        if not source_path.is_file() or not target.is_file():
            continue
        try:
            current = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if obsolete_marker not in current:
            continue
        backup = target.with_suffix(target.suffix + ".legacy-backup")
        if not backup.exists():
            shutil.copy2(target, backup)
        shutil.copy2(source_path, target)


def _load_user_experiment_plugin(manifest_path: Path) -> ExperimentPlugin | None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("type") != "experiment" or not manifest.get("enabled", True):
        return None
    manifest_id = manifest.get("id")
    try:
        validate_plugin_id(manifest_id)
    except ValueError as error:
        raise ValueError(
            f"Invalid experiment plug-in id in {manifest_path}: {error}"
        ) from error
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
    normalized_ids: set[str] = set()
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
            normalized_id = candidate.experiment_id.casefold()
            if normalized_id in normalized_ids:
                if strict:
                    raise ValueError(
                        f"Duplicate experiment plug-in id: {candidate.experiment_id}"
                    )
                continue
            normalized_ids.add(normalized_id)
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
    normalized_ids: set[str] = set()
    for info in pkgutil.iter_modules(package.__path__):
        if info.ispkg or info.name.startswith("_"):
            continue
        module = importlib.import_module(f"plugins.experiments.{info.name}")
        candidate = getattr(module, "plugin", None)
        if not isinstance(candidate, ExperimentPlugin):
            continue
        normalized_id = candidate.experiment_id.casefold()
        if normalized_id in normalized_ids:
            raise ValueError(f"Duplicate experiment plug-in id: {candidate.experiment_id}")
        normalized_ids.add(normalized_id)
        plugins[candidate.experiment_id] = candidate
    user_root = (
        Path(user_plugin_root)
        if user_plugin_root is not None
        else get_plugin_root()
    ) / "experiments"
    for experiment_id, candidate in _load_user_experiment_plugins(
        user_root, strict=strict
    ).items():
        normalized_id = experiment_id.casefold()
        if normalized_id in normalized_ids:
            raise ValueError(f"Duplicate experiment plug-in id: {experiment_id}")
        normalized_ids.add(normalized_id)
        plugins[experiment_id] = candidate
    return dict(sorted(plugins.items(), key=lambda item: (item[1].order, item[0])))
