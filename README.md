# Claude Fedora Bridge

There's no Claude desktop app for Linux. So if you're on Fedora and you use
Claude in the browser, Claude can't actually *touch* your machine — it can't read
a file, run a build, check why a service is failing, or take a screenshot to see
what you're looking at.

This is my fix for that. It's a small local server that speaks
[MCP](https://modelcontextprotocol.io) and hands the browser version of Claude a
set of tools for driving this box: look at the system, read and write files in a
workspace, build and test projects, read logs, launch apps, grab a screenshot,
and ask for root when it genuinely needs it (you get a normal Fedora password
prompt and decide).

The browser stays the UI. Claude stays the brain. This just gives it hands.

```
  Claude in your browser  ──MCP over HTTPS──►  this bridge  ──►  your Fedora machine
       (the thinking)                          (the tools)        (stuff actually happens)
```

## What you need

- Fedora (it leans on `journalctl`, `pkexec`, `lspci`, etc. — should work on most
  systemd distros with small tweaks)
- `python3` and `ssh` (both already there on a stock Fedora install)
- A **paid Claude plan** (Pro/Max/Team). Custom connectors are a paid feature, and
  Anthropic's servers call your bridge from the cloud, which is why it has to be
  reachable over a public URL.

No virtualenv. The deps go straight into your user account with `pip --user`.

## Getting started

```bash
git clone https://github.com/Cx188/Bridge-MCP-for-Claude-Users-on-Fedora.git
cd Bridge-MCP-for-Claude-Users-on-Fedora
./run.sh
```

First run installs two Python packages (`mcp`, `uvicorn`) into your account, opens
a public tunnel, and prints something like:

```
● connected
Paste this into claude.ai → Settings → Connectors:
   https://abcd-1234.a.pinggy.link/mcp-XXXXXXXX
```

Copy that URL, go to **claude.ai → Settings → Connectors → Add custom connector**,
paste it, save. Claude picks up the tools and you're good. Ask it something like
"what's using all my disk?" or "build the project in ~/ClaudeWorkspace/foo and
tell me why the tests fail."

**Keep the terminal window open** — that's the on switch. Close it (or Ctrl+C) and
everything stops immediately: the server, the tunnel, the public URL. There's no
separate disconnect step, and nothing keeps running in the background or starts
at boot.

Prefer clicking an icon? Run `./install.sh` once and you get a **Connect**
launcher on your desktop.

## About that URL

The tunnel is [Pinggy](https://pinggy.io) over SSH on port 443, because that's the
one thing that reliably gets out of locked-down networks. The catch with the free
tier: the URL changes every time you start it, and a session caps out around 60
minutes, so you re-paste occasionally. If that annoys you, a reserved domain from
Pinggy Pro or ngrok gives you a URL that never changes — same setup, just swap the
tunnel command in `run.sh`.

## What Claude can do once it's connected

- **Look around** — OS/CPU/memory/disk overview, full hardware inventory, a quick
  health check (failed services, disk/memory pressure, heavy processes), and read
  the systemd journal with filters.
- **Files** — list directories, read files, write files, spin up a new project
  folder with git initialised.
- **Build & test** — run any command, or `run_build` / `run_tests` which sniff out
  cargo, npm, meson, cmake, make, or pyproject and do the right thing.
- **Desktop** — take a screenshot (so it can literally see your screen), launch an
  app, pop a notification.
- **Root, with your say-so** — when something needs admin rights it calls
  `request_root_action`, which triggers a Polkit dialog on your screen. You type
  your password or you don't. Claude never gets root on its own.

## How safe is this, honestly

Let's be real about it, because you're pointing the internet at your laptop:

- **Reads** go anywhere you can read — *except* credential stores. `~/.ssh`,
  `~/.gnupg`, keyrings, `id_rsa`, `.netrc`, recovery codes and friends are blocked
  outright.
- **Writes and deletes** are locked to one workspace (`~/ClaudeWorkspace` by
  default) unless you deliberately run in full-access mode.
- **Root** is never automatic in the normal mode. It's always a pkexec/Polkit
  prompt that *you* approve.
- **The public URL is the lock.** The path has a random secret in it
  (`/mcp-<secret>`, stored in `~/.config/claude-fedora-bridge/url-secret`). Anyone
  with the full URL can reach the tools, so treat it like a password — don't paste
  it in public. Rotate it any time with `--rotate-secret`.
- It only runs while the window's open. When you're done, close it.

If you want to hand Claude the whole machine with no prompts — the "run everything
as root" idea — that exists too, but you have to opt in explicitly and start it as
root:

```bash
sudo PYTHONPATH=src python3 -m claude_fedora_bridge.server --full-access
```

Don't do that on a machine you care about. Use a VM.

## Running it by hand

`run.sh` is just convenience. If you want to run the server bare (say, behind your
own tunnel):

```bash
pip install --user -r requirements.txt
PYTHONPATH=src python3 -m claude_fedora_bridge.server
```

It binds to `127.0.0.1:8747` and prints the local endpoint. Point whatever tunnel
you like at that port.

## Stuff I might add

Real GUI automation (clicking and typing into windows, not just screenshots), and
maybe making the same tools work with other browser AI agents. No promises.

## Notes

Not affiliated with Anthropic — just a thing I built to make my own setup less
annoying. MIT licensed, do whatever you want with it.
