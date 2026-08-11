from core.plugin_manager import ExperimentPlugin, SequenceCommand


def create_panel(manager, parent):
    from .panel import ExperimentPanel
    return ExperimentPanel(manager, parent)


plugin = ExperimentPlugin(
    experiment_id='thermo',
    display_name='Thermo',
    panel_factory=create_panel,
    sequence_commands=(
        SequenceCommand(
            key="set_value", label="Set Value", unit="",
            minimum=0.0, maximum=100.0, default=0.0, decimals=2,
        ),
    ),
    description="User experiment panel",
    order=100,
)
