"""Runtime configuration for the bridge.

Two modes:
  standard    — user-space actions run directly; anything needing root goes
                through pkexec so Polkit shows the human a GUI approval dialog.
  full-access — no approval prompts; privileged commands run directly.
                Only honored when the server itself was started as root
                (e.g. `sudo claude-fedora-bridge --full-access`).
"""

from __future__ import annotations

import argparse
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path(
    os.environ.get("BRIDGE_CONFIG_DIR", Path.home() / ".config" / "claude-fedora-bridge")
)
SECRET_FILE = CONFIG_DIR / "url-secret"

DEFAULT_WORKSPACE = Path.home() / "ClaudeWorkspace"


@dataclass
class Config:
    mode: str = "standard"  # "standard" | "full-access"
    host: str = "127.0.0.1"
    port: int = 8747
    workspace: Path = field(default_factory=lambda: DEFAULT_WORKSPACE)
    url_secret: str = ""
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_origins: list[str] = field(default_factory=list)

    @property
    def full_access(self) -> bool:
        return self.mode == "full-access"

    @property
    def mcp_path(self) -> str:
        # The secret in the URL path is the only thing standing between a
        # tunnel URL and the whole machine — treat it like a password.
        return f"/mcp-{self.url_secret}"


def _load_or_create_secret() -> str:
    if SECRET_FILE.exists():
        value = SECRET_FILE.read_text().strip()
        if value:
            return value
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(24)
    SECRET_FILE.write_text(value + "\n")
    SECRET_FILE.chmod(0o600)
    return value


def load(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(
        prog="claude-fedora-bridge",
        description="Local MCP server that lets browser Claude work on this Fedora machine.",
    )
    parser.add_argument("--host", default=os.environ.get("BRIDGE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("BRIDGE_PORT", "8747")))
    parser.add_argument(
        "--workspace",
        default=os.environ.get("BRIDGE_WORKSPACE", str(DEFAULT_WORKSPACE)),
        help="Directory Claude may freely create and modify projects in (standard mode).",
    )
    parser.add_argument(
        "--full-access",
        action="store_true",
        default=os.environ.get("BRIDGE_MODE", "") == "full-access",
        help="DANGEROUS: skip all approval prompts. Requires running the server as root.",
    )
    parser.add_argument(
        "--rotate-secret",
        action="store_true",
        help="Generate a new URL secret (invalidates the old connector URL).",
    )
    args = parser.parse_args(argv)

    if args.rotate_secret and SECRET_FILE.exists():
        SECRET_FILE.unlink()

    mode = "standard"
    if args.full_access:
        if os.geteuid() != 0:
            parser.error(
                "--full-access requires running as root (sudo claude-fedora-bridge --full-access). "
                "Refusing to start a half-privileged full-access server."
            )
        mode = "full-access"

    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    # Always trust the local bind; add any tunnel hostnames via BRIDGE_ALLOWED_HOSTS.
    allowed_hosts = [
        f"{args.host}:{args.port}",
        f"127.0.0.1:{args.port}",
        f"localhost:{args.port}",
        "127.0.0.1",
        "localhost",
    ]
    allowed_origins: list[str] = []
    extra = os.environ.get("BRIDGE_ALLOWED_HOSTS", "").strip()
    if extra:
        for h in (x.strip() for x in extra.split(",") if x.strip()):
            allowed_hosts.append(h)
            # Tunnels reach us over TLS; trust the matching https origin too.
            allowed_origins.append(h if "://" in h else f"https://{h}")

    return Config(
        mode=mode,
        host=args.host,
        port=args.port,
        workspace=workspace,
        url_secret=_load_or_create_secret(),
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )
