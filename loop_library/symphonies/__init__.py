"""Named symphonies — pre-built instrument pipeline configurations."""

from loop_library.symphonies.magenta import create_magenta_symphony

SYMPHONY_REGISTRY: dict[str, callable] = {
    "magenta": create_magenta_symphony,
}

__all__ = ["SYMPHONY_REGISTRY", "create_magenta_symphony"]
