"""MCP server entrypoint: stdio by default, streamable HTTP with --http."""

import argparse
import logging

from wadi_config import get_settings
from wadi_mcp.server import create_server
from wadi_mcp.service import WadiMcpService
from wadi_storage import GraphRepository, GraphStore, WadiDatabase, create_client


def main() -> None:
    parser = argparse.ArgumentParser(description="wadi MCP server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="serve streamable HTTP instead of stdio (for shared deployments)",
    )
    args = parser.parse_args()

    # stdio transport: stderr only — stdout belongs to the protocol.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    settings = get_settings()
    client = create_client(settings.mongo_uri)
    database = WadiDatabase(client, settings.mongo_database)
    # Both transports need only connection strings (§8) — the driver connects
    # lazily, so stdio startup stays instant even if Neo4j is down.
    store = GraphStore(
        settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password.get_secret_value()
    )
    service = WadiMcpService(database, GraphRepository(store, database=settings.neo4j_database))
    server = create_server(service)

    if args.http:
        # Container-internal bind; host exposure is loopback-bound by compose (§13).
        server.run(transport="streamable-http", host="0.0.0.0", port=settings.mcp_port)
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
