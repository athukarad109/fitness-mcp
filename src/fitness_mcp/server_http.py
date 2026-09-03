from . import config
from .server import mcp


def configure(host: str, port: int):
    """Point the shared FastMCP instance at the given bind host/port."""
    mcp.settings.host = host
    mcp.settings.port = port
    return mcp


def build_app():
    """Return the streamable-http ASGI app for the fitness MCP server."""
    return mcp.streamable_http_app()


def main() -> None:
    host, port = config.mcp_host(), config.mcp_port()
    configure(host, port)
    print(f"fitness MCP (streamable-http) listening on http://{host}:{port}/mcp")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
