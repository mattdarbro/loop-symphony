"""Custom exceptions for Loop Symphony."""


class DepthExceededError(Exception):
    """Raised when spawn depth exceeds max_depth limit."""

    def __init__(self, current_depth: int, max_depth: int) -> None:
        self.current_depth = current_depth
        self.max_depth = max_depth
        super().__init__(
            f"Spawn depth exceeded: attempted depth={current_depth}, max={max_depth}"
        )
