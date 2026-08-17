from core.plugin_manager import ExperimentPlugin


def create_panel(manager, parent):
    from .panel import LineProfilePanel

    return LineProfilePanel(manager, parent)


plugin = ExperimentPlugin(
    experiment_id="line_profile",
    display_name="Line Profile Analysis",
    panel_factory=create_panel,
    description="Live line profiles, profile animation, and kymograph analysis",
    order=20,
)
