"""Build dist/audacity4-<version>.mcpb, the one-click Claude Desktop extension.

    python scripts/build_mcpb.py

Assembles a staging directory (manifest, entry point, the server4 package and a
dependency-only pyproject for the uv runtime) and packs it with the official
`mcpb` CLI via npx. Requires Node.js.
"""

import json
import re
import shutil
import subprocess  # noqa: S404
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGE = ROOT / "dist" / "mcpb-stage"
MCPB = "@anthropic-ai/mcpb@2.1.2"


def main() -> int:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    deps = re.search(r"^dependencies = \[(.*?)^\]", pyproject, re.M | re.S).group(1)
    deps = [d for d in re.findall(r'"([^"]+)"', deps)]

    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != version:
        print(f"extension/manifest.json version {manifest['version']} != pyproject {version}")
        return 1

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    shutil.copy(ROOT / "extension" / "manifest.json", STAGE)
    shutil.copy(ROOT / "extension" / "run_server.py", STAGE)
    shutil.copy(ROOT / "LICENSE", STAGE)
    if (ROOT / "extension" / "icon.png").exists():
        shutil.copy(ROOT / "extension" / "icon.png", STAGE)
    shutil.copytree(ROOT / "server4", STAGE / "server4",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    # Dependencies only: the host's uv installs these, and server4 is imported
    # from the bundle directory rather than built as a package.
    (STAGE / "pyproject.toml").write_text(
        "[project]\n"
        'name = "audacity4-mcp-extension"\n'
        f'version = "{version}"\n'
        'requires-python = ">=3.10"\n'
        "dependencies = [" + ", ".join(json.dumps(d) for d in deps) + "]\n\n"
        "[tool.uv]\npackage = false\n",
        encoding="utf-8",
    )

    out = ROOT / "dist" / f"audacity4-{version}.mcpb"
    npx = shutil.which("npx")
    if not npx:
        print("npx not found - install Node.js to pack the bundle.")
        return 1
    for args in (["validate", str(STAGE / "manifest.json")], ["pack", str(STAGE), str(out)]):
        r = subprocess.run([npx, "-y", MCPB, *args])  # noqa: S603
        if r.returncode != 0:
            return r.returncode
    print(f"\nBuilt {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
