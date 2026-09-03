import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("FITNESS_MCP_DATA_DIR")
    if override:
        p = Path(override)
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        p = Path(base) / "fitness-mcp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def raw_dir() -> Path:
    p = data_dir() / "raw"
    p.mkdir(parents=True, exist_ok=True)
    return p


def receiver_host() -> str:
    return os.environ.get("FITNESS_MCP_HOST", "0.0.0.0")


def receiver_port() -> int:
    return int(os.environ.get("FITNESS_MCP_PORT", "8765"))


def mcp_host() -> str:
    return os.environ.get("FITNESS_MCP_MCP_HOST", "127.0.0.1")


def mcp_port() -> int:
    return int(os.environ.get("FITNESS_MCP_MCP_PORT", "8000"))
