import sys
from typing import TextIO


class ProgressBar:
    def __init__(
        self,
        total: int,
        *,
        label: str = "",
        width: int = 36,
        stream: TextIO | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.total = total
        self.label = label
        self.width = width
        self.stream = sys.stderr if stream is None else stream
        self.current = 0
        self.enabled = self.stream.isatty() if enabled is None else enabled

    def update(self, current: int) -> None:
        self.current = current
        if self.enabled and self.total > 0:
            filled = min(self.width, int(self.width * self.current / self.total))
            bar = "█" * filled + " " * (self.width - filled)
            percent = min(100, int(100 * self.current / self.total))
            prefix = f"{self.label} " if self.label else ""
            self.stream.write(f"\r{prefix}[{bar}] {percent:3d}%")
            self.stream.flush()

    def finish(self) -> None:
        if self.enabled and self.total > 0:
            self.update(self.total)
            self.stream.write("\n")
            self.stream.flush()
