"""Generate plausible telemetry for a hydraulic press in normal operation."""

import random
from collections.abc import Callable
from datetime import UTC, datetime

from smart_factory.domain.telemetry import Telemetry


class MachineSimulator:
    """Stateful normal-operation simulator with bounded Gaussian noise."""

    def __init__(
        self,
        machine_id: str = "press-01",
        *,
        seed: int | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._machine_id = machine_id
        self._random = random.Random(seed)
        self._clock = clock or (lambda: datetime.now(UTC))

    def next_measurement(self) -> Telemetry:
        """Create the next validated measurement."""
        return Telemetry(
            machine_id=self._machine_id,
            timestamp=self._clock(),
            temperature_c=self._sample(mean=65.0, deviation=4.0, low=55.0, high=75.0),
            vibration_mm_s=self._sample(mean=2.5, deviation=0.65, low=1.0, high=4.0),
            power_kw=self._sample(mean=17.0, deviation=2.2, low=12.0, high=22.0),
            production_rate=round(self._sample(mean=42.0, deviation=3.0, low=35.0, high=50.0)),
        )

    def _sample(self, *, mean: float, deviation: float, low: float, high: float) -> float:
        value = self._random.gauss(mean, deviation)
        return round(min(high, max(low, value)), 2)
