from fitness_mcp import config


def test_data_and_raw_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FITNESS_MCP_DATA_DIR", str(tmp_path / "d"))
    assert config.data_dir() == tmp_path / "d"
    assert config.data_dir().is_dir()
    assert config.raw_dir() == tmp_path / "d" / "raw"
    assert config.raw_dir().is_dir()


def test_host_port_defaults_and_override(monkeypatch):
    monkeypatch.delenv("FITNESS_MCP_HOST", raising=False)
    monkeypatch.delenv("FITNESS_MCP_PORT", raising=False)
    assert config.receiver_host() == "0.0.0.0"
    assert config.receiver_port() == 8765
    monkeypatch.setenv("FITNESS_MCP_PORT", "9000")
    assert config.receiver_port() == 9000
