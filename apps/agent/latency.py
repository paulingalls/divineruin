import time
import logging

logger = logging.getLogger("divineruin.latency")


class TurnTimer:
    def __init__(self) -> None:
        self._stages: list[tuple[str, float]] = []
        self._start: float = 0.0

    def start(self) -> None:
        self._stages = []
        self._start = time.perf_counter()
        self._mark("turn_start")

    def mark(self, stage: str) -> None:
        self._mark(stage)

    def _mark(self, stage: str) -> None:
        self._stages.append((stage, time.perf_counter()))

    def finish(self) -> None:
        self._mark("turn_end")
        self._log()

    def _log(self) -> None:
        if len(self._stages) < 2:
            return

        total_ms = (self._stages[-1][1] - self._stages[0][1]) * 1000
        parts: list[str] = []

        for i in range(1, len(self._stages)):
            prev_name, prev_t = self._stages[i - 1]
            cur_name, cur_t = self._stages[i]
            delta_ms = (cur_t - prev_t) * 1000
            parts.append(f"{prev_name}->{cur_name}: {delta_ms:.0f}ms")

        logger.info("LATENCY total=%.0fms | %s", total_ms, " | ".join(parts))
