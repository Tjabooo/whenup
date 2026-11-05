# whenup

[![CI](https://github.com/Tjabooo/whenup/actions/workflows/ci.yml/badge.svg)](https://github.com/Tjabooo/whenup/actions/workflows/ci.yml) [![Release](https://img.shields.io/github/v/release/Tjabooo/whenup?include_prereleases&sort=semver)](https://github.com/Tjabooo/whenup/releases) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Queue shell jobs for machines that are switched off; each one runs them when it comes back up.

```console
$ whenup add laptop -t "pull dotfiles" -- 'cd ~/dotfiles && git pull && ./install.sh'
queued 20261105T151310482-9c1e for laptop: pull dotfiles

# …later, the laptop boots. 45 s after login its timer runs the job and pushes the result.

$ whenup list
nothing waiting
✓ 20261105T151310482-9c1e  laptop       2026-11-05 19:02  pull dotfiles
$ whenup show 9c1e
```

You change something on one machine and want the same change on another that's asleep.
Normally you'd have to remember it. With whenup you queue it now, and the other machine runs it
at its next boot, in order, with the output kept where every machine can see it.

## Features

- **Any git remote is the queue.** A bare repo on a home server, a private GitHub repo: whatever
  every machine can already push to over SSH. No daemon, no open port, no account.
- **Runs at boot**, then every 10 minutes (systemd user timer). It waits up to 2 minutes for the
  network to come up first.
- **Exactly once.** Each result is committed before the next job starts, so a crash or power cut
  can't run a job twice. Jobs run in the order they were queued.
- **Results travel back:** exit code, duration and the last 8 KB of output. `whenup list` and
  `whenup show` work from any machine, and the target gets a desktop notification when it runs something.
- **Works offline.** If the queue host is down, the machine runs what it already pulled and pushes
  the results later.
- Several targets at once (`whenup add desk,laptop …`), aliases (`laptop` and `laptop.lan` are
  the same machine), `cancel`, `retry`, and `--kick` to run right away if the target happens to be up.
- One Python file, standard library only.

## Install

Needs Linux with systemd, Python 3.11+ and git, plus SSH (or HTTPS) access to a git remote.

```sh
git clone https://github.com/Tjabooo/whenup ~/.local/share/whenup/src
ln -s ~/.local/share/whenup/src/whenup ~/.local/bin/whenup
```

Make a queue once, anywhere every machine can reach. It can be empty: whenup sets it up.

```sh
ssh myserver git init --bare -b main queue.git
```

Then on every machine:

```sh
whenup init myserver:queue.git          # --name desk --alias desk.lan to pick its names
whenup install-timer
```

If your user session doesn't stay running while you're logged out, `loginctl enable-linger $USER`
makes the timer run at boot rather than only once you log in.

## Usage

| Command | What it does |
| --- | --- |
| `whenup add TARGET[,TARGET] [-t TITLE] [-C DIR] [--timeout S] [--kick] -- CMD…` | Queue a job. Use `-f script.sh` or stdin for longer scripts. |
| `whenup list [TARGET] [-d N]` | Waiting jobs plus the last N results (default 5). |
| `whenup show ID` | The script and its output. Any unique ending of the id works. |
| `whenup cancel ID` / `whenup retry ID` | Drop a waiting job, or queue one that already ran again. |
| `whenup run [-n] [--wait S]` | Run this machine's jobs now. The timer calls this; `-n` only lists them. |
| `whenup kick TARGET` | Ask a machine that's up to run its queue now (over SSH). |
| `whenup status` | This machine's names, queue, timer and last run. |

Jobs run with `bash -c` as your user, in `~` unless you give `-C`, with `~/.local/bin` on `PATH`
and `WHENUP_JOB` / `WHENUP_TARGET` set. stdin is closed. A job is killed after 30 minutes by default.

```sh
# a longer script from a file, for two machines
whenup add desk,laptop -t "new fish config" -f ./migrate.sh

# piped in
echo 'systemctl --user restart waybar' | whenup add laptop -t "restart waybar"
```

## Configuration

`~/.config/whenup/config.toml`, written by `whenup init`:

```toml
queue = "myserver:queue.git"   # any git remote
name = "laptop"                # jobs for this name run here (default: hostname)
aliases = ["laptop.lan"]       # other names that mean this machine
notify = true                  # desktop notification after jobs run
shell = "bash"
timeout = 1800                 # default seconds per job

# Queue on a Windows OpenSSH server (whenup init --windows-host): cmd.exe keeps git's quotes
upload_pack = "powershell git-upload-pack"
receive_pack = "powershell git-receive-pack"
```

The paths can be moved with `WHENUP_CONFIG`, `WHENUP_DATA` (queue clone, default
`~/.local/share/whenup`) and `WHENUP_STATE` (lock and last run, default `~/.local/state/whenup`).

## How it works

The queue repo holds one JSON file per job:

```
pending/<machine>/<id>.json   waiting
done/<machine>/<id>.json      ran: the job plus a "result" (status, exit, output, times)
```

`whenup add` writes a file under `pending/` and pushes. `whenup run` pulls, runs every file under
`pending/<its names>/` oldest first, moves each one to `done/` with its result, commits after every
job and pushes at the end. Ids start with a millisecond timestamp, so they sort in queue order.
Pushes that race another machine are rebased and retried; jobs are separate files, so they never conflict.

## Security

Anyone who can push to the queue can run commands as you on every machine that reads it. Treat
push access to the queue like SSH access to those machines: keep the repo private, on a host you control.

## License

[MIT](LICENSE)
