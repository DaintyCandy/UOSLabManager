from core.plugin_manager import ExperimentPlugin, SequenceCommand


def create_panel(manager, parent):
    from .panel import HeatingControlPanel
    return HeatingControlPanel(manager, parent)


plugin = ExperimentPlugin(
    experiment_id="heating_control",
    display_name="Heating Control",
    panel_factory=create_panel,
    sequence_commands=(
        SequenceCommand(
            key="ramp_to_setpoint",
            label="Ramp to Setpoint",
            unit="°C",
            minimum=-50.0,
            maximum=2000.0,
            default=300.0,
            decimals=1,
        ),
        SequenceCommand(
            key="stop_heating",
            label="Stop Heating",
            requires_value=False,
        ),
    ),
    description="ZUP 36-12 and CTvideo 3M heating control workspace",
    order=5,
)
