from core.plugin_manager import ExperimentPlugin


def create_panel(manager, parent):
    from ._heating_control_panel import HeatingControlPanel
    return HeatingControlPanel(manager, parent)


plugin = ExperimentPlugin(
    experiment_id="heating_control",
    display_name="Heating Control",
    panel_factory=create_panel,
    description="ZUP 36-12 and CTvideo 3M heating control workspace",
    order=5,
)
