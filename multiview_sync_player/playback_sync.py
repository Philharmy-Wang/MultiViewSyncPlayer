"""Synchronization primitives shared by the playback UI and tests.

The decoder threads are intentionally asynchronous.  ``SeekBarrier`` gives a
global seek/step one generation number and only releases images after every
participating view has supplied the exact requested frame for that generation.
"""

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


@dataclass
class SeekRequest:
    generation: int
    base_frame: int
    targets: dict[str, int]
    retry_count: int = 0
    started_at: float = field(default_factory=perf_counter)
    frames: dict[str, Any] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.targets.keys() <= self.frames.keys()

    @property
    def missing_views(self) -> list[str]:
        return [view for view in self.targets if view not in self.frames]

    @property
    def latency_ms(self) -> float:
        return (perf_counter() - self.started_at) * 1000.0


class SeekBarrier:
    """Reject stale decoder callbacks and collect one atomic UI commit."""

    def __init__(self):
        self._generation = 0
        self.active: SeekRequest | None = None

    @property
    def generation(self) -> int:
        return self._generation

    def begin(self, base_frame: int, targets: dict[str, int],
              retry_count: int = 0) -> SeekRequest:
        self._generation += 1
        self.active = SeekRequest(
            generation=self._generation,
            base_frame=base_frame,
            targets=dict(targets),
            retry_count=retry_count,
        )
        return self.active

    def accept(self, generation: int, view: str, frame_number: int,
               image: Any) -> bool:
        """Accept an exact latest-generation result; return completion state."""
        request = self.active
        if request is None or generation != request.generation:
            return False
        if request.targets.get(view) != frame_number:
            return False
        request.frames[view] = image
        return request.complete

    def finish(self, generation: int) -> SeekRequest | None:
        request = self.active
        if request is None or request.generation != generation:
            return None
        if not request.complete:
            return None
        self.active = None
        return request

    def cancel(self, generation: int) -> None:
        if self.active and self.active.generation == generation:
            self.active = None
