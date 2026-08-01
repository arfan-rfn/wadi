"""Wadi MCP server (architecture.md §8)."""

from wadi_mcp.server import create_server
from wadi_mcp.service import WadiMcpService

__all__ = ["WadiMcpService", "create_server"]
