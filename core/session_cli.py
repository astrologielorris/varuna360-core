# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Find and run the Claude Code / Codex CLIs from the desktop app.

Shared by the AI Providers login check and the chart image import, which use
the user's existing CLI subscription instead of an API key.

A desktop app does not inherit the shell PATH: launched from Finder, the Dock,
the Start menu or a desktop entry it sees only the system directories, so a CLI
installed by npm, Homebrew or its own installer is "not found" although it runs
fine in a terminal. The search below adds the places those installers use.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys


def _cli_search_dirs():
    home = os.path.expanduser("~")
    dirs = [os.path.join(home, ".local", "bin"),
            os.path.join(home, ".npm-global", "bin"),
            os.path.join(home, ".bun", "bin"),
            os.path.join(home, ".volta", "bin"),
            os.path.join(home, ".cargo", "bin")]
    dirs += sorted(glob.glob(os.path.join(home, ".nvm", "versions", "node", "*", "bin")),
                   reverse=True)
    if sys.platform == "win32":
        for var in ("APPDATA", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                dirs.append(os.path.join(base, "npm"))
    else:
        dirs += ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
    return [d for d in dirs if os.path.isdir(d)]


def find_cli(binary):
    """Full path of a session CLI, looking past the app's own PATH."""
    return shutil.which(binary) or shutil.which(
        binary, path=os.pathsep.join(_cli_search_dirs()))


def cli_env(path):
    """Environment for running a CLI: its own directory and the usual install
    directories go on PATH, because an npm-installed CLI is a node script that
    must also find `node`, which the desktop PATH lacks too."""
    env = dict(os.environ)
    extra = [os.path.dirname(path)] + _cli_search_dirs()
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


def run_cli(path, args, timeout, input_text=None, cwd=None):
    """Run a CLI and capture its output as UTF-8 text.

    UTF-8 explicitly: Node CLIs write UTF-8, and Windows would otherwise decode
    with the ANSI code page and fail on an accented name. On Windows the CLI
    runs without a console window.
    """
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if input_text is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = input_text
    return subprocess.run([path, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=timeout, check=False, env=cli_env(path),
                          cwd=cwd, **kwargs)
