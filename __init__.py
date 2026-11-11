"""Last Price (Hermes plugin entry point)."""

try:
    from .last_price import register
except ImportError:  # pytest imports the plugin root as a bare module while collecting tests/
    from last_price import register

__all__ = ["register"]
