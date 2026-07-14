"""Permission model.

Standard mode:
  * reads: anywhere the user can read, except a denylist of credential stores
  * writes/deletes: only inside the configured workspace
  * privileged commands: routed through pkexec, so Polkit pops a GUI dialog
    and the human decides — root is always controlled by the user.

Full-access mode: every check passes; privileged commands run directly.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from .config import Config

# Credential material Claude has no business reading even in standard mode.
SENSITIVE_DIRS = (".ssh", ".gnupg", ".pki", ".password-store", ".local/share/keyrings")
SENSITIVE_NAMES = ("id_rsa", "id_ed25519", ".netrc", "credentials", "secret", "recovery-codes")

MAX_OUTPUT = 30_000  # chars of command output returned to the model


class PermissionError_(Exception):
    """Raised when an operation is outside what the current mode allows."""


def _resolve(path: str) -> Path:
    return Path(path).expanduser().resolve()


def check_read(cfg: Config, path: str) -> Path:
    p = _resolve(path)
    if cfg.full_access:
        return p
    rel_home = p.as_posix()
    for d in SENSITIVE_DIRS:
        if f"/{d}/" in rel_home + "/" and str(Path.home()) in rel_home:
            raise PermissionError_(
                f"Reading {p} is blocked: it lives under a credential store (~/{d}). "
                "Ask the user to share the specific content if it is really needed."
            )
    lowered = p.name.lower()
    for n in SENSITIVE_NAMES:
        if n in lowered:
            raise PermissionError_(
                f"Reading {p} is blocked: the filename looks like credential material."
            )
    return p


def check_write(cfg: Config, path: str) -> Path:
    p = _resolve(path)
    if cfg.full_access:
        return p
    if not p.is_relative_to(cfg.workspace):
        raise PermissionError_(
            f"Writing outside the workspace is not allowed in standard mode. "
            f"Workspace: {cfg.workspace}. Requested: {p}. "
            "Create the file inside the workspace, or ask the user to move the "
            "workspace / restart the bridge with --full-access."
        )
    return p


def run_user_command(command: str, cwd: str | None = None, timeout: int = 300) -> str:
    """Run an ordinary user-space shell command and return combined output."""
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"[timed out after {timeout}s] command: {command}"
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + f"\n… [truncated, {len(out)} chars total]"
    return f"[exit {proc.returncode}]\n{out.strip()}" if out.strip() else f"[exit {proc.returncode}] (no output)"


def run_privileged_command(cfg: Config, command: str, reason: str, timeout: int = 300) -> str:
    """Run a command as root.

    Standard mode: wraps it in pkexec. Polkit raises a GUI authentication
    dialog on the user's desktop; the command only runs if the human approves.
    Full-access mode: runs directly (the server is already root).
    """
    if cfg.full_access:
        return run_user_command(command, timeout=timeout)

    # pkexec needs a polkit agent on the active desktop session; the dialog it
    # shows *is* the user approval step of the permission model.
    wrapped = f"pkexec bash -c {shlex.quote(command)}"
    result = run_user_command(wrapped, timeout=timeout)
    if "[exit 126]" in result or "[exit 127]" in result:
        result += (
            "\n[bridge] The Polkit dialog was dismissed, failed, or no polkit agent "
            "is available. The user did NOT approve this action. Reason given: "
            + reason
        )
    return result


def describe_mode(cfg: Config) -> str:
    if cfg.full_access:
        return (
            "FULL-ACCESS mode: the bridge runs as root and executes everything "
            "without prompting. Be careful and conservative on the user's behalf."
        )
    return (
        f"STANDARD mode: user-space actions run directly; writes are confined to "
        f"{cfg.workspace}; anything needing root triggers a Polkit GUI dialog the "
        "user must approve. Always pass an honest 'reason' when requesting root."
    )


def is_root() -> bool:
    return os.geteuid() == 0
