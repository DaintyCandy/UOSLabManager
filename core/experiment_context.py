"""Stable host services exposed to experiment plug-ins."""


class DeviceAccess:
    def __init__(self, manager):
        self._manager = manager

    def get(self, device_id):
        return self._manager.get_device(device_id)

    def latest(self, device_id):
        return self._manager.get_latest(device_id)

    def metrics(self, device_id):
        return self._manager.get_metrics(device_id)

    def all_latest(self):
        return self._manager.read_all()


class CameraAccess:
    def __init__(self, workspace):
        self._workspace = workspace

    def frame_packet(self, camera_index=0):
        """Return ``(BGR frame copy, sequence)`` only during live preview."""
        return self._workspace.get_frame_packet(camera_index)

    def latest_frame(self, camera_index=0):
        frame, _sequence = self.frame_packet(camera_index)
        return frame

    def borrow_frame_packet(self, camera_index=0):
        """Borrow a frame for immediate GUI-thread analysis without copying it."""
        return self._workspace.borrow_frame_packet(camera_index)

    def route_preview(self, target, camera_index=0, owner=None):
        """Move the one live preview renderer to an experiment plug-in view."""
        return self._workspace.route_preview(target, camera_index, owner)

    def release_preview(self, owner):
        self._workspace.release_preview(owner)


class ExperimentAccess:
    def __init__(self, panel_resolver):
        self._panel_resolver = panel_resolver

    def panel(self, experiment_id, *, create=False):
        return self._panel_resolver(experiment_id, create=create)

    def execute(self, experiment_id, command, value):
        panel = self.panel(experiment_id, create=True)
        if panel is None or not hasattr(panel, "execute_sequence_command"):
            raise RuntimeError(f"Experiment command is unavailable: {experiment_id}")
        return panel.execute_sequence_command(command, value)

    def is_complete(self, experiment_id, command, value):
        panel = self.panel(experiment_id)
        return bool(
            panel is not None
            and panel.is_sequence_command_complete(command, value)
        )


class ExperimentContext:
    """Versioned façade passed as the first panel-factory argument.

    Direct methods retain compatibility with the former DeviceManager argument.
    New plug-ins should use ``devices``, ``data``, ``cameras``, and ``experiments``.
    """

    api_version = 1

    def __init__(self, manager, camera_workspace, panel_resolver):
        self.devices = DeviceAccess(manager)
        self.data = self.devices
        self.cameras = CameraAccess(camera_workspace)
        self.experiments = ExperimentAccess(panel_resolver)

    def get_device(self, name):
        return self.devices.get(name)

    def get_latest(self, name):
        return self.devices.latest(name)

    def get_metrics(self, name):
        return self.devices.metrics(name)

    def read_all(self):
        return self.devices.all_latest()
