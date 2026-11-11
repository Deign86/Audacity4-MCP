import json
import sys

import pytest

from server4 import installer


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "_home", lambda: tmp_path)
    monkeypatch.setattr(installer.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    return tmp_path


LAUNCH = installer.Launch("/py", ["-m", "server4"], {"AUDACITY4_MCP_PROFILE": "mastering"})


def test_json_merge_keeps_other_servers_and_keys(home):
    path = installer.claude_desktop_config()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"keep": {"command": "k"}}, "other": 1}))

    assert installer.set_json_server(path, LAUNCH) is True
    data = json.loads(path.read_text())
    assert data["other"] == 1
    assert data["mcpServers"]["keep"] == {"command": "k"}
    assert data["mcpServers"]["audacity4"]["env"]["AUDACITY4_MCP_PROFILE"] == "mastering"
    assert (path.parent / "claude_desktop_config.json.bak").exists()

    assert installer.set_json_server(path, LAUNCH) is False  # idempotent
    assert installer.set_json_server(path, None) is True
    assert "audacity4" not in json.loads(path.read_text())["mcpServers"]


def test_json_refuses_invalid_file(home):
    path = installer.claude_desktop_config()
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    with pytest.raises(SystemExit):
        installer.set_json_server(path, LAUNCH)
    assert path.read_text() == "{not json"


def test_codex_replaces_only_its_own_tables(home):
    tomllib = pytest.importorskip("tomllib")
    path = installer.codex_config()
    path.parent.mkdir(parents=True)
    path.write_text(
        'model = "m"\n\n[mcp_servers.other]\ncommand = "x"\n\n'
        '[mcp_servers.audacity4]\ncommand = "old"\n[mcp_servers.audacity4.env]\nA = "1"\n\n'
        '[profiles.p]\nmodel = "y"\n'
    )
    installer.set_codex_server(path, LAUNCH)
    cfg = tomllib.loads(path.read_text())
    assert cfg["model"] == "m"
    assert cfg["mcp_servers"]["other"] == {"command": "x"}
    assert cfg["profiles"]["p"] == {"model": "y"}
    ours = cfg["mcp_servers"]["audacity4"]
    assert ours["command"] == "/py" and ours["args"] == ["-m", "server4"]
    assert ours["env"] == {"AUDACITY4_MCP_PROFILE": "mastering"}
    assert ours["startup_timeout_sec"] >= 60

    installer.set_codex_server(path, None)
    cfg = tomllib.loads(path.read_text())
    assert "audacity4" not in cfg["mcp_servers"]
    assert cfg["mcp_servers"]["other"] == {"command": "x"}


def test_codex_creates_file(home):
    path = installer.codex_config()
    assert installer.set_codex_server(path, LAUNCH) is True
    assert path.read_text().startswith("[mcp_servers.audacity4]")


def test_antigravity_prefers_existing_legacy_location(home):
    assert installer.antigravity_config() == home / ".gemini" / "config" / "mcp_config.json"
    legacy = home / ".gemini" / "antigravity" / "mcp_config.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}")
    assert installer.antigravity_config() == legacy


def test_claude_code_entry_has_stdio_type(home):
    out = installer.apply("claude-code", LAUNCH, use_cli=False)
    assert "registered" in out
    entry = json.loads((home / ".claude.json").read_text())["mcpServers"]["audacity4"]
    assert entry["type"] == "stdio" and entry["command"] == "/py"


def test_uvx_launcher_uses_source(home):
    launch = installer.resolve_launch("uvx", None, "git+https://example/repo")
    assert launch.args == ["--from", "git+https://example/repo", "audacity4-mcp"]
    assert launch.env == {}


def test_print_config_writes_nothing(home, capsys):
    assert installer.cli(["print-config", "--launcher", "python"]) == 0
    assert "[mcp_servers.audacity4]" in capsys.readouterr().out
    assert not any(home.iterdir())


@pytest.mark.parametrize("before, after", [
    (None, "[mcp]\nenabled=true\n"),
    ("foo=1\n", "foo=1\n\n[mcp]\nenabled=true\n"),
    ("[ui]\nenabled=false\n", "[ui]\nenabled=false\n\n[mcp]\nenabled=true\n"),
    ("[mcp]\nenabled=false\n[ui]\nx=1\n", "[mcp]\nenabled=true\n[ui]\nx=1\n"),
    ("[mcp]\nport=1\n[ui]\nenabled=false\n", "[mcp]\nenabled=true\nport=1\n[ui]\nenabled=false\n"),
])
def test_enable_bridge_only_touches_mcp_section(home, before, after):
    path = installer.audacity_settings_file()
    assert path == home / ".config" / "Audacity" / "Audacity4Development.ini"
    if before is not None:
        path.parent.mkdir(parents=True)
        path.write_text(before)
    assert installer.bridge_enabled(path) is False
    assert installer.enable_bridge(path) is True
    assert path.read_text() == after
    assert installer.bridge_enabled(path) is True
    assert installer.enable_bridge(path) is False  # idempotent


def test_settings_file_on_windows(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(home / "Roaming"))
    assert installer.audacity_settings_file() == home / "Roaming" / "Audacity" / "Audacity4Development.ini"


def test_unknown_command_exits_instead_of_starting_server(monkeypatch, capsys):
    from server4 import cli
    monkeypatch.setattr(sys, "argv", ["audacity4-mcp", 'doctor"C:\\x\\audacity4-mcp.exe"', "install"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 2
    assert "unknown command" in capsys.readouterr().err
