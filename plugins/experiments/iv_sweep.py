from dataclasses import dataclass

from core.plugin_manager import ExperimentPlugin


@dataclass(frozen=True)
class IVSweep:
    start_voltage: float
    stop_voltage: float
    points: int
    current_limit: float = 0.01

    def recipe_steps(self):
        if self.points < 2:
            raise ValueError("IV sweep requires at least two points.")
        increment = (self.stop_voltage - self.start_voltage) / (self.points - 1)
        voltages = [self.start_voltage + increment * index for index in range(self.points)]
        return (
            [{"dev": "K2400", "cmd": "Output On", "val": 0}]
            + [{"dev": "K2400", "cmd": "Set Voltage", "val": value} for value in voltages]
            + [{"dev": "K2400", "cmd": "Output Off", "val": 0}]
        )


def create_default_recipe():
    return IVSweep(start_voltage=0.0, stop_voltage=1.0, points=11).recipe_steps()


plugin = ExperimentPlugin(
    experiment_id="iv_sweep",
    display_name="I-V Sweep",
    recipe_factory=create_default_recipe,
    description="K2400 voltage sweep recipe",
    order=20,
)
