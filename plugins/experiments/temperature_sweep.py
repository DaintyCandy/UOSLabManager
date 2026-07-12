from dataclasses import dataclass


@dataclass(frozen=True)
class TemperatureSweep:
    start_temperature: float
    stop_temperature: float
    rate: float
