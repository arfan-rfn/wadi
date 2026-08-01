"""Wadi configuration — 12-factor from day zero (architecture.md §13).

All service config comes from ``WADI_``-prefixed environment variables (with
``.env`` support), read through this one settings package. Backing services
are attached resources identified by URI — never assumed to be sibling
containers. No service hardcodes a dependency address.
"""

from wadi_config.settings import WadiSettings, get_settings

__all__ = ["WadiSettings", "get_settings"]
