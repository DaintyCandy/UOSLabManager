from dataclasses import dataclass


@dataclass(frozen=True)
class IVSweep:
    start_voltage: float
    stop_voltage: float
    points: int
    current_limit: float = 0.01
