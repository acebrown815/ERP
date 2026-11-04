#!/usr/bin/env python3
"""Run the local servers from one place, in the background, with logs in .dev/. Windows: `py` instead of `python`.

    python tools/dev.py start [all|db|api|worker|web]     all is the default
    python tools/dev.py restart [all|db|api|worker|web]
    python tools/dev.py stop [all|db|api|worker|web]      all leaves the database running
    python tools/dev.py status
    python tools/dev.py logs api|worker|web|db [lines]

It also finds servers started by hand, so a restart never needs a process hunt. It only ever stops a process it
can identify as this repo's server: anything else holding one of the ports is reported and left alone.

Restart the web server when status says its memory is high: `next dev` keeps what each rebuild uses, and pages get
slow long before it runs out. Restart the API after changing API code.

Standard library only, so it runs with any Python before the API's virtualenv is even set up.
"""

import argparse
import contextlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / ".dev"
WINDOWS = sys.platform == "win32"
# Pages stayed fast at 2.1 GB and took 6 seconds after a rebuild at 3.6 GB; Node's default limit is about 4 GB.
WEB_MEMORY_WARNING_MB = 2500


def _api_python() -> str:
    return str(ROOT / "apps/api/.venv" / ("Scripts/python.exe" if WINDOWS else "bin/python"))


@dataclass(frozen=True)
class Service:
    name: str
    cwd: str
    signature: str  # matched against the command lines of python and node processes that mention this repo
    port: int | None = None
    url: str | None = None  # answers when the service is ready
    wait_seconds: int = 60

    def command(self) -> list[str]:
        if self.name == "api":
            return [_api_python(), "-m", "uvicorn", "app.main:app", "--port", str(self.port)]
        if self.name == "worker":
            return [_api_python(), "-m", "app.worker"]
        return [shutil.which("npm") or "npm", "run", "dev"]


API = Service(
    "api",
    "apps/api",
    r"uvicorn(\.exe)?[\"']?\s+app\.main:app",
    port=8000,
    url="http://127.0.0.1:8000/api/health",
)
WORKER = Service("worker", "apps/api", r"-m\s+app\.worker")
WEB = Service(
    "web",
    "apps/web",
    r"next[\\/]dist[\\/](bin[\\/]next[\"']?\s+dev|server[\\/]lib[\\/]start-server)",
    port=3000,
    url="http://localhost:3000/login",
    wait_seconds=180,
)
SERVERS = {s.name: s for s in (API, WORKER, WEB)}
DB_PORT = 54329


# ---- processes ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Proc:
    pid: int
    parent: int
    name: str
    memory_mb: float
    command: str


def list_processes() -> list[Proc]:
    if WINDOWS:
        script = (
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
            "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,WorkingSetSize,CommandLine"
            " | ConvertTo-Json -Compress"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script], capture_output=True, encoding="utf-8", check=True
        ).stdout
        return [
            Proc(
                p["ProcessId"],
                p["ParentProcessId"],
                p["Name"] or "",
                (p["WorkingSetSize"] or 0) / 1048576,
                p["CommandLine"] or "",
            )
            for p in json.loads(out)
        ]
    out = subprocess.run(["ps", "-eo", "pid=,ppid=,rss=,args="], capture_output=True, text=True, check=True).stdout
    procs = []
    for line in out.splitlines():
        pid, parent, rss, command = line.split(None, 3)
        procs.append(Proc(int(pid), int(parent), Path(command.split()[0]).name, int(rss) / 1024, command))
    return procs


def belongs_to(service: Service, proc: Proc, root: Path = ROOT) -> bool:
    """A python or node process running this service from this repo. Shells quoting the same text don't count."""
    if not re.match(r"(python|uvicorn|node)", proc.name, re.I):
        return False
    if str(root).replace("\\", "/").lower() not in proc.command.replace("\\", "/").lower():
        return False
    return re.search(service.signature, proc.command) is not None


def _descendants(pid: int, procs: list[Proc]) -> list[Proc]:
    found, frontier = [], [pid]
    while frontier:
        children = [p for p in procs if p.parent in frontier and p not in found]
        found += children
        frontier = [p.pid for p in children]
    return found


def running(service: Service, procs: list[Proc]) -> list[Proc]:
    """The topmost processes of the service: stopping one takes its children with it."""
    matched = [p for p in procs if belongs_to(service, p)]
    ids = {p.pid for p in matched}
    return [p for p in matched if p.parent not in ids]


def memory_mb(roots: list[Proc], procs: list[Proc]) -> float:
    seen = {p.pid: p for root in roots for p in [root, *_descendants(root.pid, procs)]}
    return sum(p.memory_mb for p in seen.values())


def port_open(port: int) -> bool:
    """Something is listening on the port. On Windows this asks the system: connecting and hanging up straight away
    makes the API log a ConnectionResetError traceback."""
    if WINDOWS:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, check=False).stdout
        for line in out.splitlines():
            parts = line.split()  # the state column is translated on some systems; a listener has no remote end
            if len(parts) >= 3 and parts[1].endswith(f":{port}") and parts[2] in ("0.0.0.0:0", "[::]:0"):
                return True
        return False
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def kill_tree(proc: Proc, procs: list[Proc]) -> None:
    if WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
        return
    for p in [*_descendants(proc.pid, procs), proc]:
        with contextlib.suppress(ProcessLookupError):
            os.kill(p.pid, 15)


# ---- actions ------------------------------------------------------------------------------------------------


def _wait(test, seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if test():
            return True
        time.sleep(0.5)
    return test()


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=120):  # the first request to a page compiles it
            return True
    except urllib.error.HTTPError:
        return True  # it answered
    except OSError:
        return False


def log_path(name: str) -> Path:
    return LOGS / f"{name}.log"


def _tail(name: str, lines: int = 15) -> str:
    path = log_path(name)
    if not path.exists():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def _spawn(service: Service) -> subprocess.Popen:
    LOGS.mkdir(exist_ok=True)
    flags = {}
    if WINDOWS:
        # A hidden console of its own: it keeps running when this terminal closes, and nothing pops up on screen.
        flags["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        flags["start_new_session"] = True
    with log_path(service.name).open("w", encoding="utf-8") as log:
        return subprocess.Popen(
            service.command(),
            cwd=ROOT / service.cwd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            **flags,
        )


def start_db() -> bool:
    if port_open(DB_PORT):
        print(f"db      already running on port {DB_PORT}")
        return True
    devdb = ROOT / "tools/devdb"
    if not (devdb / "node_modules").exists():
        print(
            "db      not running, and tools/devdb isn't installed: run `npm install` there, or start your own database"
        )
        return False
    LOGS.mkdir(exist_ok=True)
    with log_path("db").open("w", encoding="utf-8") as log:
        done = subprocess.run(
            ["node", "devdb.mjs", "start"],
            cwd=devdb,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if done.returncode != 0 or not port_open(DB_PORT):
        print(f"db      failed to start:\n{_tail('db')}")
        return False
    print(f"db      started on port {DB_PORT}")
    return True


def stop_db() -> bool:
    devdb = ROOT / "tools/devdb"
    if not port_open(DB_PORT):
        print("db      not running")
        return True
    if not (devdb / "node_modules").exists():
        print(f"db      something else is on port {DB_PORT}; leaving it alone")
        return False
    subprocess.run(["node", "devdb.mjs", "stop"], cwd=devdb, capture_output=True, check=False)
    stopped = _wait(lambda: not port_open(DB_PORT), 15)
    print("db      stopped" if stopped else "db      still running")
    return stopped


def start(service: Service) -> bool:
    procs = list_processes()
    roots = running(service, procs)
    if roots:
        print(f"{service.name:7} already running (pid {roots[0].pid})")
        return True
    if service.port and port_open(service.port):
        print(f"{service.name:7} port {service.port} is in use by something else; stop that first")
        return False
    if service.name in ("api", "worker") and not Path(_api_python()).exists():
        print(f"{service.name:7} apps/api/.venv is missing: see README, Local development")
        return False
    print(f"{service.name:7} starting…", flush=True)
    process = _spawn(service)
    if service.url:
        ok = _wait(
            lambda: process.poll() is None and bool(service.port and port_open(service.port)), service.wait_seconds
        )
        ok = ok and _answers(service.url)
    else:
        time.sleep(3)
        ok = process.poll() is None
    if not ok:
        print(f"{service.name:7} failed to start. Log ({log_path(service.name)}):\n{_tail(service.name)}")
        return False
    print(f"{service.name:7} running{f' at {service.url}' if service.url else ''}")
    return True


def stop(service: Service) -> bool:
    procs = list_processes()
    roots = running(service, procs)
    if not roots:
        if service.port and port_open(service.port):
            print(f"{service.name:7} port {service.port} is held by something else; leaving it alone")
            return False
        print(f"{service.name:7} not running")
        return True
    for root in roots:
        kill_tree(root, procs)

    def gone() -> bool:
        free = not (service.port and port_open(service.port))
        return free and not running(service, list_processes())

    if not _wait(gone, 20):
        print(f"{service.name:7} did not stop in time")
        return False
    print(f"{service.name:7} stopped")
    return True


def status() -> bool:
    procs = list_processes()
    print(f"{'db':8}{'running' if port_open(DB_PORT) else 'stopped':10}{'':>10}  port {DB_PORT}")
    advice = []
    for service in SERVERS.values():
        roots = running(service, procs)
        held = bool(service.port and port_open(service.port))
        state = "running" if roots else ("unknown" if held else "stopped")
        mb = memory_mb(roots, procs) if roots else 0
        memory = f"{mb:,.0f} MB" if roots else ""
        where = service.url.rsplit("/api", 1)[0].removesuffix("/login") if service.url else ""
        print(f"{service.name:8}{state:10}{memory:>10}  {where}")
        if held and not roots:
            advice.append(f"Port {service.port} is held by something this script can't identify.")
        if service is WEB and mb > WEB_MEMORY_WARNING_MB:
            advice.append("The web server's memory is high and pages will get slow: python tools/dev.py restart web")
    for line in advice:
        print(f"\n{line}")
    return True


def expand(target: str, *, with_db: bool) -> list[str]:
    if target != "all":
        return [target]
    return (["db"] if with_db else []) + list(SERVERS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local servers.")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("start", "stop", "restart"):
        sub.add_parser(action).add_argument("target", nargs="?", default="all", choices=["all", "db", *SERVERS])
    sub.add_parser("status")
    logs = sub.add_parser("logs")
    logs.add_argument("target", choices=["db", *SERVERS])
    logs.add_argument("lines", nargs="?", type=int, default=40)
    args = parser.parse_args()

    if args.action == "status":
        return 0 if status() else 1
    if args.action == "logs":
        print(_tail(args.target, args.lines) or f"No log yet: {log_path(args.target)}")
        return 0

    ok = True
    if args.action in ("stop", "restart"):
        # `all` leaves the database up: restarting the app shouldn't drop it.
        for name in expand(args.target, with_db=False):
            ok = (stop_db() if name == "db" else stop(SERVERS[name])) and ok
    if args.action in ("start", "restart") and ok:
        for name in expand(args.target, with_db=args.action == "start"):
            ok = (start_db() if name == "db" else start(SERVERS[name])) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
