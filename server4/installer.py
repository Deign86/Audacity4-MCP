"""`audacity4-mcp install | uninstall | doctor | print-config`.

Registers this server with MCP clients so nobody has to hand-edit JSON or
TOML: Claude Code, Claude Desktop, OpenAI Codex and Google Antigravity.

Every write is a merge: only the `audacity4` entry is touched, everything else
in the client's config is left byte-for-byte alone where the format allows
(TOML is edited as text for that reason - there is no stdlib TOML writer, and
round-tripping through one would reformat the user's whole file). A `.bak` copy
is written next to any file that already existed before it is changed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import socket
import subprocess  # noqa: S404 - only runs the `claude` CLI, with fixed args
import sys
from dataclasses import dataclass, field
from pathlib import Path

SERVER_NAME = "audacity4"
# Where `uvx` installs from when the server is not already installed locally.
# Overridable so a fork can point its users at itself.
DEFAULT_SOURCE = os.environ.get(
    "AUDACITY4_MCP_SOURCE", "git+https://github.com/xDarkzx/Audacity4-MCP"
)
CLIENTS = ("claude-code", "claude-desktop", "codex", "antigravity")
BRIDGE_HOST, BRIDGE_PORT = "127.0.0.1", 2212


# --------------------------------------------------------------------------
# What to launch
# --------------------------------------------------------------------------

@dataclass
class Launch:
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    def as_json_entry(self) -> dict:
        entry: dict = {"command": self.command, "args": self.args}
        if self.env:
            entry["env"] = self.env
        return entry


def _running_from_ephemeral_env() -> bool:
    """True when this process lives in a uv/pipx-run throwaway environment.

    Writing that interpreter's path into a client config would work today and
    break whenever uv garbage-collects its cache, so those get a `uvx` launcher.
    """
    prefix = Path(sys.prefix).as_posix().lower()
    return "/uv/archive-v" in prefix or "/uv/builds-v" in prefix or "/pipx/.cache/" in prefix


def resolve_launch(launcher: str, profile: str | None, source: str) -> Launch:
    env = {"AUDACITY4_MCP_PROFILE": profile} if profile else {}
    if launcher == "auto":
        launcher = "uvx" if _running_from_ephemeral_env() else "python"
    if launcher == "uvx":
        uvx = shutil.which("uvx") or "uvx"
        return Launch(uvx, ["--from", source, "audacity4-mcp"], env)
    if launcher == "python":
        # The absolute interpreter path sidesteps the most common failure in
        # the old instructions: the client not seeing a venv's bin dir on PATH.
        return Launch(sys.executable, ["-m", "server4"], env)
    if launcher == "path":
        exe = shutil.which("audacity4-mcp")
        if not exe:
            raise SystemExit("audacity4-mcp is not on PATH; use --launcher python or uvx.")
        return Launch(exe, [], env)
    raise SystemExit(f"Unknown launcher {launcher!r}")


# --------------------------------------------------------------------------
# Where each client keeps its config
# --------------------------------------------------------------------------

def _home() -> Path:
    return Path.home()


def claude_desktop_config() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", _home() / "AppData" / "Roaming")) / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(_home() / ".config")
    return Path(xdg) / "Claude" / "claude_desktop_config.json"


def claude_code_config() -> Path:
    return _home() / ".claude.json"


def codex_config() -> Path:
    return Path(os.environ.get("CODEX_HOME") or _home() / ".codex") / "config.toml"


def antigravity_config() -> Path:
    """Antigravity's documented global file is ~/.gemini/config/mcp_config.json;
    earlier builds read ~/.gemini/antigravity/mcp_config.json. Use whichever the
    installed version already has, preferring the documented one."""
    documented = _home() / ".gemini" / "config" / "mcp_config.json"
    legacy = _home() / ".gemini" / "antigravity" / "mcp_config.json"
    if not documented.exists() and legacy.exists():
        return legacy
    return documented


CONFIG_PATHS = {
    "claude-code": claude_code_config,
    "claude-desktop": claude_desktop_config,
    "codex": codex_config,
    "antigravity": antigravity_config,
}


# --------------------------------------------------------------------------
# Editing
# --------------------------------------------------------------------------

def _backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))


def _read_json(path: Path) -> dict:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"{path} is not valid JSON ({e}); fix or move it, then retry.") from e
    if not isinstance(data, dict):
        raise SystemExit(f"{path} does not contain a JSON object; refusing to edit it.")
    return data


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def set_json_server(path: Path, launch: Launch | None) -> bool:
    """Add/replace (launch) or remove (None) the entry. Returns True if changed."""
    data = _read_json(path)
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise SystemExit(f"'mcpServers' in {path} is not an object; refusing to edit it.")
    if launch is None:
        if SERVER_NAME not in servers:
            return False
        del servers[SERVER_NAME]
    else:
        entry = launch.as_json_entry()
        if path == claude_code_config():
            entry = {"type": "stdio", **entry}
        if servers.get(SERVER_NAME) == entry:
            return False
        servers[SERVER_NAME] = entry
    _write_json(path, data)
    return True


def _toml_str(s: str) -> str:
    return json.dumps(s)  # a JSON string is a valid TOML basic string


def codex_block(launch: Launch) -> str:
    lines = [
        f"[mcp_servers.{SERVER_NAME}]",
        f"command = {_toml_str(launch.command)}",
        "args = [" + ", ".join(_toml_str(a) for a in launch.args) + "]",
        # uvx may build an environment on first launch; Codex's 10s default is too short.
        "startup_timeout_sec = 120",
        # Mastering pipelines on long files legitimately run for minutes.
        "tool_timeout_sec = 600",
    ]
    if launch.env:
        lines.append("")
        lines.append(f"[mcp_servers.{SERVER_NAME}.env]")
        lines += [f"{k} = {_toml_str(v)}" for k, v in launch.env.items()]
    return "\n".join(lines) + "\n"


_TABLE_HEADER = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")


def _strip_codex_block(text: str) -> tuple[str, bool]:
    """Remove [mcp_servers.audacity4] and its sub-tables, keep everything else."""
    out, skipping, removed = [], False, False
    ours = f"mcp_servers.{SERVER_NAME}"
    for line in text.splitlines(keepends=True):
        m = _TABLE_HEADER.match(line)
        if m:
            name = m.group(1).replace('"', "").replace("'", "")
            skipping = name == ours or name.startswith(ours + ".")
            removed |= skipping
        if not skipping:
            out.append(line)
    return "".join(out), removed


def set_codex_server(path: Path, launch: Launch | None) -> bool:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    stripped, had = _strip_codex_block(text)
    if launch is None:
        if not had:
            return False
        new = stripped.rstrip() + ("\n" if stripped.strip() else "")
    else:
        body = stripped.rstrip()
        new = (body + "\n\n" if body else "") + codex_block(launch)
    if new == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    path.write_text(new, encoding="utf-8")
    return True


def _try_claude_cli(launch: Launch | None) -> bool | None:
    """Prefer `claude mcp add/remove` when the CLI is installed: it owns the
    file format. Returns None if the CLI is unavailable so the caller can fall
    back to editing ~/.claude.json directly."""
    claude = shutil.which("claude")
    if not claude:
        return None
    subprocess.run([claude, "mcp", "remove", "--scope", "user", SERVER_NAME],  # noqa: S603
                   capture_output=True, text=True)
    if launch is None:
        return True
    cmd = [claude, "mcp", "add", "--scope", "user"]
    for k, v in launch.env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += [SERVER_NAME, "--", launch.command, *launch.args]
    r = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    if r.returncode != 0:
        sys.stderr.write(f"  `claude mcp add` failed ({r.stderr.strip()}); editing config directly.\n")
        return None
    return True


def apply(client: str, launch: Launch | None, use_cli: bool = True) -> str:
    path = CONFIG_PATHS[client]()
    if client == "claude-code" and use_cli:
        if _try_claude_cli(launch) is not None:
            return f"{client}: {'registered' if launch else 'removed'} via `claude mcp` (user scope)"
    if client == "codex":
        changed = set_codex_server(path, launch)
    else:
        changed = set_json_server(path, launch)
    verb = ("registered" if launch else "removed") if changed else "already up to date"
    return f"{client}: {verb} -> {path}"


def detect_clients() -> list[str]:
    """Clients that look installed: their config dir exists or their CLI is on PATH."""
    found = []
    if shutil.which("claude") or claude_code_config().exists():
        found.append("claude-code")
    if claude_desktop_config().parent.exists():
        found.append("claude-desktop")
    if shutil.which("codex") or codex_config().parent.exists():
        found.append("codex")
    if (_home() / ".gemini").exists() or shutil.which("antigravity") or shutil.which("agy"):
        found.append("antigravity")
    return found


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------

def doctor() -> int:
    from server4.bridge_client import BridgeClient

    ok = True
    print(f"python         {sys.executable} ({sys.version.split()[0]})")

    client = BridgeClient()
    try:
        token = client._resolve_token()
        src = "AUDACITY4_MCP_TOKEN" if os.environ.get("AUDACITY4_MCP_TOKEN", "").strip() else "profile file"
        print(f"token          found ({src}, {len(token)} chars)")
    except RuntimeError as e:
        print(f"token          MISSING - {e}")
        ok = False

    try:
        with socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=2):
            print(f"bridge         listening on {BRIDGE_HOST}:{BRIDGE_PORT}")
        port_open = True
    except OSError as e:
        print(f"bridge         NOT reachable on {BRIDGE_HOST}:{BRIDGE_PORT} ({e}).")
        print("               Start the Audacity4 MCP fork, and make sure its [mcp] enabled=true.")
        port_open = ok = False

    if port_open and ok:
        async def probe():
            try:
                await client.call("recent-commands", {})
            finally:
                await client.close()
        try:
            asyncio.run(probe())
            print("auth           OK - an authenticated read-only call succeeded")
        except RuntimeError as e:
            print(f"auth           FAILED - {e}")
            ok = False

    for c in CLIENTS:
        path = CONFIG_PATHS[c]()
        state = "not configured"
        try:
            if c == "codex":
                if path.exists() and _strip_codex_block(path.read_text(encoding="utf-8"))[1]:
                    state = "configured"
            elif SERVER_NAME in _read_json(path).get("mcpServers", {}):
                state = "configured"
        except SystemExit as e:
            state = f"unreadable ({e})"
        print(f"{c:<15}{state} ({path})")

    print("\nAll good." if ok else "\nProblems found - see above.")
    return 0 if ok else 1


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _resolve_targets(names: list[str] | None) -> list[str]:
    if not names:
        return detect_clients()
    if "all" in names:
        return list(CLIENTS)
    return names


def cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="audacity4-mcp", description="Audacity 4 MCP server")
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("--client", "-c", action="append", choices=[*CLIENTS, "all"],
                        help="Client to configure (repeatable). Default: every client detected on this machine.")
        sp.add_argument("--no-claude-cli", action="store_true",
                        help="Edit ~/.claude.json directly instead of running `claude mcp`.")

    sp_i = sub.add_parser("install", help="Register this server with MCP clients")
    common(sp_i)
    sp_i.add_argument("--profile", choices=["full", "cleanup", "editing", "mastering", "transcription", "minimal"],
                      help="Tool profile to load (fewer tools = less context per turn).")
    sp_i.add_argument("--launcher", choices=["auto", "python", "uvx", "path"], default="auto",
                      help="How clients start the server. auto: this Python, or uvx when run via uvx.")
    sp_i.add_argument("--source", default=DEFAULT_SOURCE, help="Package spec uvx installs from.")

    sp_u = sub.add_parser("uninstall", help="Remove this server from MCP clients")
    common(sp_u)

    sub.add_parser("doctor", help="Check token, bridge connection and client configs")

    sp_p = sub.add_parser("print-config", help="Print config snippets without writing anything")
    sp_p.add_argument("--profile")
    sp_p.add_argument("--launcher", choices=["auto", "python", "uvx", "path"], default="uvx")
    sp_p.add_argument("--source", default=DEFAULT_SOURCE)

    a = p.parse_args(argv)

    if a.cmd == "doctor":
        return doctor()

    if a.cmd == "print-config":
        launch = resolve_launch(a.launcher, a.profile, a.source)
        print("# Claude Desktop / Claude Code / Antigravity (mcpServers JSON)")
        print(json.dumps({"mcpServers": {SERVER_NAME: launch.as_json_entry()}}, indent=2))
        print("\n# Codex (~/.codex/config.toml)")
        print(codex_block(launch))
        return 0

    if a.cmd in ("install", "uninstall"):
        targets = _resolve_targets(a.client)
        if not targets:
            print("No MCP clients detected. Name one with --client "
                  f"({', '.join(CLIENTS)}, or all).")
            return 1
        launch = resolve_launch(a.launcher, a.profile, a.source) if a.cmd == "install" else None
        if launch:
            print(f"Server command: {launch.command} {' '.join(launch.args)}")
        for c in targets:
            print("  " + apply(c, launch, use_cli=not a.no_claude_cli))
        if launch:
            print("\nRestart those apps to pick it up. Then run `audacity4-mcp doctor` "
                  "with Audacity open to check the connection.")
        return 0

    p.print_help()
    return 0
