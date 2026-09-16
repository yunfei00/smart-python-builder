class BuildEngineError(RuntimeError):
    """Base error for build-engine failures."""


class BuildCommandError(BuildEngineError):
    """Raised when an external build command exits unsuccessfully."""
