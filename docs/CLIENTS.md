# Installing in Claude, Codex and Antigravity

The server is the same everywhere; only how each client starts it differs.
Audacity 4 (the MCP-enabled [companion fork](../README.md#building-the-companion-fork))
must be running for any tool call to work.

Every route below starts the server through [uv](https://docs.astral.sh/uv/),
which fetches Python and the dependencies itself. Install it once:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Fastest: one command for every client

```bash
uvx --from git+https://github.com/xDarkzx/Audacity4-MCP audacity4-mcp install
```

That detects which of Claude Code, Claude Desktop, Codex and Antigravity are
installed and registers the server with each. It also switches the bridge on in
Audacity4-Dev-MCP's settings (`[mcp] enabled=true`, off by default), so there is
no `.ini` to edit by hand; pass `--no-enable-bridge` to skip that, or run
`audacity4-mcp enable-bridge` on its own. Only the `audacity4` entry in
each config is written; everything else is left as it was, and a `.bak` copy is
saved first. Useful flags:

| Flag | Effect |
|---|---|
| `--client codex` (repeatable), `--client all` | Configure only these clients / all of them |
| `--profile mastering` | Load a smaller tool set ([profiles](../README.md#tool-profiles)) |
| `--launcher python` | Point clients at the current Python instead of `uvx` (use after `pip install`) |

Then restart the apps and check everything end to end, with Audacity open:

```bash
uvx --from git+https://github.com/xDarkzx/Audacity4-MCP audacity4-mcp doctor
```

`doctor` checks that the token is readable, the bridge is listening on
127.0.0.1:2212, an authenticated call succeeds, and which clients are
configured. `audacity4-mcp uninstall` reverses `install`;
`audacity4-mcp print-config` prints every snippet below without writing anything.

## Claude Desktop: one-click extension

Download `audacity4-<version>.mcpb` from the
[releases page](https://github.com/xDarkzx/Audacity4-MCP/releases) and
double-click it (or drag it onto Claude Desktop → Settings → Extensions). Claude
Desktop installs Python and the dependencies itself. The extension settings
have a **Tool profile** option; leave **Bridge token override** empty unless
`doctor` says the token cannot be found.

Build it yourself with `python scripts/build_mcpb.py` (needs Node.js); the file
lands in `dist/`.

## Claude Code: plugin (server + mastering skill)

```text
/plugin install audacity4 --marketplace xDarkzx/Audacity4-MCP
```

(On Claude Code versions before 2.1.275: `/plugin marketplace add xDarkzx/Audacity4-MCP`, then `/plugin install audacity4@audacity4-mcp`.)

That adds the MCP server. Or add it directly:

```bash
claude mcp add --scope user audacity4 -- uvx --from git+https://github.com/xDarkzx/Audacity4-MCP audacity4-mcp
```

## OpenAI Codex

```bash
codex mcp add audacity4 -- uvx --from git+https://github.com/xDarkzx/Audacity4-MCP audacity4-mcp
```

or in `~/.codex/config.toml`:

```toml
[mcp_servers.audacity4]
command = "uvx"
args = ["--from", "git+https://github.com/xDarkzx/Audacity4-MCP", "audacity4-mcp"]
startup_timeout_sec = 120   # first launch builds an environment
tool_timeout_sec = 600      # mastering pipelines on long files take minutes

[mcp_servers.audacity4.env]
AUDACITY4_MCP_PROFILE = "full"
```

The two timeouts matter: Codex's defaults (10 s startup, 60 s per tool) are too
short for a cold `uvx` start and for whole-file pipelines.

## Google Antigravity

Agent panel → **…** → **MCP Servers** → **Manage MCP Servers** → **View raw
config**, and add:

```json
{
  "mcpServers": {
    "audacity4": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/xDarkzx/Audacity4-MCP", "audacity4-mcp"],
      "env": { "AUDACITY4_MCP_PROFILE": "full" }
    }
  }
}
```

The global file is `~/.gemini/config/mcp_config.json` (some earlier builds used
`~/.gemini/antigravity/mcp_config.json`; `install` writes whichever exists).

## Anything else that speaks MCP

Run `uvx --from git+https://github.com/xDarkzx/Audacity4-MCP audacity4-mcp` as a
stdio server. Cursor, Windsurf, VS Code and Gemini CLI all accept the same
`mcpServers` JSON shown above.

## If the client says "Unauthorized"

The `audacity4-mcp` 0.1.0 release on PyPI predates token authentication and
sends no token, so the current Audacity fork rejects every call. Use any route
above (they install from this repository), or `pip install -U audacity4-mcp`
once 0.2.0 is published, then run `doctor`.
