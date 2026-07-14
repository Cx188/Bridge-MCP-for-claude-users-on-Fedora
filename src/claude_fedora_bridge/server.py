"""MCP server entry point.

This is the actual bridge: a FastMCP server that hands the browser Claude a set
of tools for driving this Fedora box. Start it with `./run.sh` (which also opens
the Pinggy tunnel), then paste the printed URL into claude.ai as a custom
connector.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image
from mcp.server.transport_security import TransportSecuritySettings

from . import config as config_mod
from . import security
from .security import PermissionError_, run_privileged_command, run_user_command

CFG = config_mod.load()

mcp = FastMCP(
    name="Claude Fedora Bridge",
    instructions=(
        "You are connected to the user's Fedora Linux workstation through the "
        "Claude Fedora Bridge. You can inspect the system, manage projects, "
        "read/write files, build, test, read logs, take screenshots and launch "
        "apps. " + security.describe_mode(CFG)
    ),
    host=CFG.host,
    port=CFG.port,
    streamable_http_path=CFG.mcp_path,
    stateless_http=True,
    # DNS-rebinding protection stays ON. Because the bridge is reached through a
    # tunnel, we must allowlist the tunnel's Host header explicitly (set via
    # BRIDGE_ALLOWED_HOSTS). Any Host not on the list is still rejected, so a
    # rebinding attacker pointing a hostname at 127.0.0.1 gets a 421.
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=CFG.allowed_hosts,
        allowed_origins=CFG.allowed_origins,
    ),
)


def _sh(cmd: str, timeout: int = 30) -> str:
    return run_user_command(cmd, timeout=timeout)


# ---------------------------------------------------------------- system ----

@mcp.tool()
def system_overview() -> str:
    """Get an overview of this machine: OS, kernel, CPU, memory, disks, desktop, uptime."""
    parts = {
        "OS": _sh("cat /etc/fedora-release"),
        "Kernel": platform.release(),
        "Hostname": platform.node(),
        "Uptime": _sh("uptime -p"),
        "CPU": _sh("lscpu | grep -E 'Model name|^CPU\\(s\\)' | sed 's/  */ /g'"),
        "Memory": _sh("free -h | head -3"),
        "Disks": _sh("df -h -x tmpfs -x devtmpfs --output=target,size,used,avail,pcent"),
        "Desktop": os.environ.get("XDG_CURRENT_DESKTOP", "unknown")
        + " / "
        + os.environ.get("XDG_SESSION_TYPE", "unknown"),
        "Bridge mode": CFG.mode,
        "Workspace": str(CFG.workspace),
    }
    return "\n\n".join(f"## {k}\n{v}" for k, v in parts.items())


@mcp.tool()
def hardware_info() -> str:
    """Detailed hardware inventory: CPU, PCI devices (GPU, network), USB, memory modules."""
    return "\n\n".join(
        [
            "## CPU\n" + _sh("lscpu"),
            "## PCI\n" + _sh("lspci"),
            "## USB\n" + _sh("lsusb"),
            "## Block devices\n" + _sh("lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT"),
        ]
    )


@mcp.tool()
def system_health() -> str:
    """Quick diagnosis: failed services, disk pressure, memory pressure, heaviest processes."""
    return "\n\n".join(
        [
            "## Failed systemd units\n" + _sh("systemctl --failed --no-pager"),
            "## Disk usage\n" + _sh("df -h -x tmpfs -x devtmpfs"),
            "## Memory\n" + _sh("free -h"),
            "## Top processes by memory\n"
            + _sh("ps aux --sort=-%mem | head -12"),
            "## Top processes by CPU\n" + _sh("ps aux --sort=-%cpu | head -12"),
        ]
    )


@mcp.tool()
def read_logs(unit: str = "", since: str = "1 hour ago", lines: int = 200, grep: str = "") -> str:
    """Read systemd journal logs. Optionally filter by unit (e.g. 'NetworkManager'),
    time window (journalctl --since syntax), and a grep pattern."""
    cmd = f"journalctl --no-pager -n {int(lines)} --since '{since}'"
    if unit:
        cmd += f" -u '{unit}'"
    if grep:
        cmd += f" | grep -iE '{grep}' | tail -n {int(lines)}"
    return _sh(cmd, timeout=60)


# ----------------------------------------------------------------- files ----

@mcp.tool()
def list_directory(path: str = "~") -> str:
    """List a directory (names, sizes, type). Defaults to the user's home."""
    p = security.check_read(CFG, path)
    if not p.is_dir():
        return f"Not a directory: {p}"
    rows = []
    for child in sorted(p.iterdir(), key=lambda c: (c.is_file(), c.name.lower())):
        try:
            kind = "dir " if child.is_dir() else "file"
            size = "" if child.is_dir() else f" {child.stat().st_size:,} B"
            rows.append(f"{kind}  {child.name}{size}")
        except OSError:
            rows.append(f"?     {child.name}")
    return f"{p} ({len(rows)} entries)\n" + "\n".join(rows[:500])


@mcp.tool()
def read_file(path: str, max_bytes: int = 60_000) -> str:
    """Read a text file from disk."""
    p = security.check_read(CFG, path)
    data = p.read_bytes()[: int(max_bytes)]
    try:
        return data.decode()
    except UnicodeDecodeError:
        return f"[binary file, {p.stat().st_size:,} bytes] {p}"


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write (create or overwrite) a text file. In standard mode the path must be
    inside the workspace."""
    p = security.check_write(CFG, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Wrote {len(content):,} chars to {p}"


@mcp.tool()
def create_project(name: str, description: str = "") -> str:
    """Create a new project directory inside the workspace and initialize git."""
    p = security.check_write(CFG, str(CFG.workspace / name))
    p.mkdir(parents=True, exist_ok=True)
    if description:
        (p / "README.md").write_text(f"# {name}\n\n{description}\n")
    git = _sh(f"git -C {p} init -q && echo git-initialized || echo git-unavailable")
    return f"Project created at {p} ({git.splitlines()[-1]})"


# ------------------------------------------------------------ build/test ----

_BUILD_DETECT = [
    ("Cargo.toml", "cargo build", "cargo test"),
    ("package.json", "npm install && npm run build --if-present", "npm test --if-present"),
    ("meson.build", "meson setup build --wipe 2>/dev/null; meson compile -C build", "meson test -C build"),
    ("CMakeLists.txt", "cmake -B build && cmake --build build", "ctest --test-dir build"),
    ("Makefile", "make", "make test"),
    ("pyproject.toml", "python3 -m pip install -e . --quiet && echo installed", "python3 -m pytest"),
]


def _detect(project_dir: Path, index: int) -> str | None:
    for marker, build, test in _BUILD_DETECT:
        if (project_dir / marker).exists():
            return (build, test)[index]
    return None


@mcp.tool()
def run_command(command: str, cwd: str = "", timeout: int = 300) -> str:
    """Run a user-space shell command and return exit code + output.
    Root-level commands will fail here — use request_root_action instead."""
    workdir = cwd or str(CFG.workspace)
    return run_user_command(command, cwd=workdir, timeout=int(timeout))


@mcp.tool()
def run_build(project_path: str, command: str = "") -> str:
    """Build a project. Auto-detects cargo/npm/meson/cmake/make/pyproject if no
    command is given."""
    p = security.check_read(CFG, project_path)
    cmd = command or _detect(p, 0)
    if not cmd:
        return f"No known build system detected in {p}; pass an explicit command."
    return f"$ {cmd}\n" + run_user_command(cmd, cwd=str(p), timeout=900)


@mcp.tool()
def run_tests(project_path: str, command: str = "") -> str:
    """Run a project's test suite. Auto-detects the test runner if no command is given."""
    p = security.check_read(CFG, project_path)
    cmd = command or _detect(p, 1)
    if not cmd:
        return f"No known test runner detected in {p}; pass an explicit command."
    return f"$ {cmd}\n" + run_user_command(cmd, cwd=str(p), timeout=900)


# --------------------------------------------------------------- desktop ----

_SCREENSHOT_TOOLS = [
    "gnome-screenshot -f {out}",
    "spectacle -b -n -o {out}",
    "grim {out}",
    "scrot {out}",
]


@mcp.tool()
def capture_screenshot():
    """Capture the current desktop screen and return it as an image."""
    out = Path(tempfile.mkstemp(suffix=".png", prefix="bridge-shot-")[1])
    last = "no screenshot tool found (install gnome-screenshot, spectacle, grim, or scrot)"
    for template in _SCREENSHOT_TOOLS:
        tool = template.split()[0]
        if not shutil.which(tool):
            continue
        last = run_user_command(template.format(out=out), timeout=30)
        if out.exists() and out.stat().st_size > 0:
            return Image(path=str(out))
    return (
        "Screenshot failed. No working tool among gnome-screenshot/spectacle/grim/scrot, "
        "or the bridge is not running inside the desktop session. "
        f"Last output: {last}"
    )


@mcp.tool()
def launch_application(command: str) -> str:
    """Launch a desktop application detached from the bridge (e.g. 'firefox',
    'gtk4-demo', './build/myapp')."""
    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=str(CFG.workspace),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(1.0)
    alive = proc.poll() is None
    return f"Launched '{command}' (pid {proc.pid}, {'running' if alive else f'exited immediately with code {proc.returncode}'})"


@mcp.tool()
def send_notification(title: str, body: str = "") -> str:
    """Show a desktop notification to the user."""
    if not shutil.which("notify-send"):
        return "notify-send not available."
    return _sh(f"notify-send {title!r} {body!r} && echo sent")


# ------------------------------------------------------------ privileged ----

@mcp.tool()
def request_root_action(command: str, reason: str, risk: str = "low") -> str:
    """Request a command that needs administrator privileges.

    In standard mode this raises a Polkit GUI dialog on the user's desktop —
    the command runs only if the human approves. Always explain honestly:
      command — the exact command to run as root
      reason  — why it is needed for the current task
      risk    — low / medium / high, your honest assessment
    """
    if not reason.strip():
        return "Refused: a non-empty 'reason' is required for root actions."
    header = f"[root request] risk={risk}\nreason: {reason}\ncommand: {command}\n\n"
    return header + run_privileged_command(CFG, command, reason)


@mcp.tool()
def bridge_status() -> str:
    """Describe the bridge itself: mode, permission model, workspace, version."""
    from . import __version__

    return (
        f"Claude Fedora Bridge v{__version__}\n"
        f"Mode: {CFG.mode}\n"
        f"Running as root: {security.is_root()}\n"
        f"Workspace: {CFG.workspace}\n\n"
        + security.describe_mode(CFG)
    )


# ------------------------------------------------------------------ main ----

def main() -> None:
    banner_url = f"http://{CFG.host}:{CFG.port}{CFG.mcp_path}"
    print("Claude Fedora Bridge", file=sys.stderr)
    print(f"  mode:      {CFG.mode}", file=sys.stderr)
    if CFG.full_access:
        print(
            "  *** FULL ACCESS: running as root with no approval prompts. ***",
            file=sys.stderr,
        )
    print(f"  workspace: {CFG.workspace}", file=sys.stderr)
    print(f"  endpoint:  {banner_url}", file=sys.stderr)
    print(
        "  this is the local endpoint. run.sh puts a public Pinggy URL in front of\n"
        f"  it; paste that URL (ending in {CFG.mcp_path}) into claude.ai → Connectors.",
        file=sys.stderr,
    )
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
