from fitness_mcp import config, server_http


def test_mcp_host_port_defaults_and_override(monkeypatch):
    monkeypatch.delenv("FITNESS_MCP_MCP_HOST", raising=False)
    monkeypatch.delenv("FITNESS_MCP_MCP_PORT", raising=False)
    assert config.mcp_host() == "127.0.0.1"
    assert config.mcp_port() == 8000
    monkeypatch.setenv("FITNESS_MCP_MCP_PORT", "8010")
    assert config.mcp_port() == 8010


def test_configure_sets_settings_and_builds_app():
    inst = server_http.configure("127.0.0.1", 8123)
    assert inst.settings.host == "127.0.0.1"
    assert inst.settings.port == 8123
    app = server_http.build_app()
    assert callable(app)  # an ASGI application
