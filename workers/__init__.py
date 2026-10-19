"""Background execution: the same loop runs inline in the API process (single node) or as ``python -m AIDAP worker``."""

from .runner import WorkerLoop

__all__ = ["WorkerLoop"]
