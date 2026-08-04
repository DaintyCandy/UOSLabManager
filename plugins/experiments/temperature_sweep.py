from dataclasses import dataclass

from core.plugin_manager import ExperimentPlugin


@dataclass(frozen=True)
class TemperatureSweep:
    start_temperature: float
    stop_temperature: float
    rate: float

    def recipe_steps(self):
        return [
            {"dev": "LS331", "cmd": "Apply Ramp", "val": self.rate},
            {"dev": "LS331", "cmd": "Set Temp", "val": self.start_temperature},
            {"dev": "LS331", "cmd": "Apply Ramp", "val": self.rate},
            {"dev": "LS331", "cmd": "Set Temp", "val": self.stop_temperature},
        ]


def create_default_recipe():
    return TemperatureSweep(
        start_temperature=300.0, stop_temperature=310.0, rate=1.0,
    ).recipe_steps()


plugin = ExperimentPlugin(
    experiment_id="temperature_sweep",
    display_name="Temperature Sweep",
    recipe_factory=create_default_recipe,
    description="LS331 temperature ramp recipe",
    order=10,
)
