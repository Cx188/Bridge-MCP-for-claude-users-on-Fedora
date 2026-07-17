# Claude Fedora Bridge

There's no Claude desktop app for Linux. So if you're on Fedora and you use
Claude in the browser This is my fix for that. 
a small local server that speaks
[MCP](https://modelcontextprotocol.io) 
basically we hand the browser a
set of tools for driving this box: look at the system, read and write files in a
workspace, build and test projects, read logs, launch apps, grab a screenshot,
and ask for root when its needed 
(you get a normal Fedora password prompt and decide).


```
  Claude in your browser  ──MCP over HTTPS──►  this bridge  ──►  your Fedora machine
       (the thinking)                          (the tools)        (stuff actually happens)
```

## What you need

- Fedora (it leans on `journalctl`, `pkexec`, `lspci`, etc. should work on most
  systemd distros with small tweaks)
- `python3` and `ssh` (both already there on a stock Fedora install)
- A **paid Claude plan** (Pro/Max/Team). Custom connectors are a paid feature, and
  Anthropic's servers call your bridge from the cloud, which is why it has to be
  reachable over a public URL.

No virtualenv. The deps go straight into your user account with `pip --user`.

## do it manually

```bash
git clone https://github.com/Cx188/Bridge-MCP-for-Claude-Users-on-Fedora.git
cd Bridge-MCP-for-Claude-Users-on-Fedora
./run.sh
```
or download the files then hit `./install.sh` once and you get a **Connect**
launcher on your desktop , open the file to start the bridge.

First run installs two Python packages (`mcp`, `uvicorn`) into your account, opens
a public tunnel, and prints the bridge status 

```
● connected
Paste this into claude.ai → Settings → Connectors:
   https://abcd-1234.a.pinggy.link/mcp-XXXXXXXX
```

Copy that URL, go to **claude → Settings → Connectors → Add custom connector**,
paste the url, save. Claude picks up the tools and you are ready. 
same windows experience 

**Keep the terminal window open** that's the on switch. Close it or Ctrl+C to close
the bridge



## About that URL

The tunnel is [Pinggy](https://pinggy.io) over SSH on port 443,its free,
The catch : the URL changes every time you start it, and a session caps out around 60
minutes, so just close , then open and paste the url again. 
or use a cloudeflare 

## all the tools

- **Look around** : OS/CPU/memory/disk overview, full hardware inventory, a quick
  health check (failed services, disk/memory pressure, heavy processes), and read
  the systemd journal with filters.
- **Files** : list directories, read files, write files, spin up a new project
  folder with git initialised.
- **Build & test** : run any command, or `run_build` / `run_tests` which sniff out
  cargo, npm, meson, cmake, make, or pyproject and do the right thing.
- **Desktop** : take a screenshot (so it can literally see your screen), launch an
  app, pop a notification.
- **Root** : when something needs admin rights it calls
  `request_root_action`, which triggers a Polkit dialog on your screen. You type
  your password or you don't. Claude never gets root on its own.
  


- **The public URL is the lock.** The path has a random secret key in it
  (`/mcp-<secret>`, stored in `~/.config/claude-fedora-bridge/url-secret`)
  don't paste it or give to anyone, you can Rotate it any time with `--rotate-secret`.
- the connection only runs while the window's open.

If you want to hand Claude the whole machine with no prompts the "run everything
as root" idea then just run the bridge as root


## Stuff I might add

Real GUI automation (clicking and typing into windows, not just screenshots), and
maybe making the same tools work with other browser AI agents. No promises.

## Notes

Not official just a thing I built to make my own setup less
annoying. MIT licensed, do whatever you want with it.
