from core.plugin_manager import ExperimentPlugin, SequenceCommand


def create_panel(manager, parent):
    from .panel import ExperimentPanel
    return ExperimentPanel(manager, parent)


plugin = ExperimentPlugin(
    experiment_id='MBE1',
    display_name='MBE Chamber Monitor',
    panel_factory=create_panel,
    sequence_commands=(
        SequenceCommand(
            key="set_temperature_setpoint", label="Set temperature setpoint", unit="°C",
            minimum=0.0, maximum=2000.0, default=25.0, decimals=1,
        ),
    ),
    description="MBE chamber camera, pyrometer, and heating-control monitor",
    order=100,
)
