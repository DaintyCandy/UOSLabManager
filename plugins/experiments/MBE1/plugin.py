from core.plugin_manager import ExperimentPlugin, SequenceCommand


def create_panel(context, parent):
    from .panel import ExperimentPanel
    return ExperimentPanel(context, parent)


plugin = ExperimentPlugin(
    experiment_id='MBE1',
    display_name='MBE Heating Monitor',
    panel_factory=create_panel,
    sequence_commands=(
        SequenceCommand(
            key="set_value", label="Heating Setpoint", unit="°C",
            minimum=-50.0, maximum=2000.0, default=300.0, decimals=1,
        ),
    ),
    description="Pyrometer, camera, notes, and heating control",
    order=100,
)
