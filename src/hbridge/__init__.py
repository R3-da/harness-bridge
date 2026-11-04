"""harness-bridge: switch coding-agent harnesses between subscriptions and API providers."""

__version__ = "0.1.0"


class HBridgeError(Exception):
    """A user-facing error: printed without a traceback, exit status 1."""
