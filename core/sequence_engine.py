from enum import Enum, auto


class SequenceState(Enum):
    IDLE = auto()
    RUNNING = auto()
    STOPPED = auto()


class SequenceEngine:
    """UI-independent state holder for experiment sequence execution."""

    def __init__(self):
        self.steps = []
        self.current_step = 0
        self.state = SequenceState.IDLE

    def load(self, steps):
        self.steps = list(steps)
        self.current_step = 0
        self.state = SequenceState.IDLE

    def start(self):
        self.state = SequenceState.RUNNING

    def stop(self):
        self.state = SequenceState.STOPPED
