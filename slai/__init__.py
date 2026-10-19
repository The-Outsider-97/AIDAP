"""SLAI adapters. Importing this package is cheap: SLAI agents are loaded lazily, on first use."""

from .orchestration import SlaiRuntime, build_slai_runtime

__all__ = ["SlaiRuntime", "build_slai_runtime"]
