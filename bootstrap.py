#!/usr/bin/env python3
"""One-command local setup.

    python bootstrap.py

Checks prerequisites, creates both .env files (generating a real JWT secret),
installs backend and frontend dependencies, verifies MongoDB is reachable, and
prints the exact commands to start the app.

Safe to re-run: existing .env files are never overwritten.
"""
from __future__ import annotations

import os
import platform
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
IS_WINDOWS = platform.system() == "Windows"

GREEN, YELLOW, RED, DIM, BOLD, RESET = (
    ("\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")
    if not IS_WINDOWS or os.environ.get("WT_SESSION")
    else ("", "", "", "", "", "")
)

problems: list[str] = []


def say(msg: str = "") -> None:
    print(msg)


def ok(msg: str) -> None:
    print(f"  {GREEN}v{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}!{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}x{RESET} {msg}")
    problems.append(msg)


def header(msg: str) -> None:
    print(f"\n{BOLD}{msg}{RESET}")


def run(cmd: list[str], cwd: Path | None = None, quiet: bool = True) -> bool:
    try:
        subprocess.run(
            cmd,
            cwd=cwd,
            check=True,
            stdout=subprocess.DEVNULL if quiet else None,
            stderr=subprocess.STDOUT if quiet else None,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def which(name: str) -> str | None:
    return shutil.which(name)


# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
def check_prerequisites() -> None:
    header("1. Prerequisites")

    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 10):
        ok(f"Python {major}.{minor}")
    else:
        fail(f"Python {major}.{minor} found, but 3.10+ is required")

    node = which("node")
    if node:
        version = subprocess.run(
            [node, "--version"], capture_output=True, text=True
        ).stdout.strip()
        number = int(version.lstrip("v").split(".")[0] or 0)
        (ok if number >= 18 else fail)(
            f"Node {version}" + ("" if number >= 18 else " — 18+ required")
        )
    else:
        fail("Node.js not found — install from https://nodejs.org")

    if which("yarn"):
        ok("yarn")
    elif which("npm"):
        warn("yarn missing; will use npm instead (works fine)")
    else:
        fail("Neither yarn nor npm found")


# ---------------------------------------------------------------------------
# 2. Configuration
# ---------------------------------------------------------------------------
def write_env_files() -> None:
    header("2. Configuration")

    backend_env = BACKEND / ".env"
    if backend_env.exists():
        ok("backend/.env already exists (left untouched)")
    else:
        template = (BACKEND / ".env.example").read_text(encoding="utf-8")
        # A real secret up front means tokens survive restarts, instead of the
        # dev fallback regenerating one and logging everybody out.
        template = template.replace("JWT_SECRET=", f"JWT_SECRET={secrets.token_hex(32)}")
        backend_env.write_text(template, encoding="utf-8")
        ok("created backend/.env with a generated JWT_SECRET")

    frontend_env = FRONTEND / ".env"
    if frontend_env.exists():
        ok("frontend/.env already exists (left untouched)")
    else:
        shutil.copy(FRONTEND / ".env.example", frontend_env)
        ok("created frontend/.env")


# ---------------------------------------------------------------------------
# 3. Backend
# ---------------------------------------------------------------------------
def venv_python() -> Path:
    return BACKEND / "venv" / ("Scripts" if IS_WINDOWS else "bin") / (
        "python.exe" if IS_WINDOWS else "python"
    )


def install_backend() -> None:
    header("3. Backend dependencies")

    if venv_python().exists():
        ok("virtual environment exists")
    else:
        say(f"  {DIM}creating virtual environment...{RESET}")
        if run([sys.executable, "-m", "venv", str(BACKEND / "venv")]):
            ok("created backend/venv")
        else:
            fail("could not create the virtual environment")
            return

    # Always re-run, even when the venv already exists: requirements.txt
    # gains packages over time (pymupdf for PDF import, for instance) and a
    # stale environment fails at the moment a user tries the new feature
    # rather than here.
    #
    # Output is NOT suppressed. pip can sit silent for a minute or more while
    # it resolves and builds, and a silent script looks like a hung one —
    # which is exactly when someone reaches for Ctrl+C.
    say(f"  {DIM}installing packages — pip output follows, this takes a minute{RESET}")
    say()
    run([str(venv_python()), "-m", "pip", "install", "--upgrade", "pip", "--quiet"])

    installed = run(
        [str(venv_python()), "-m", "pip", "install", "-r",
         str(BACKEND / "requirements.txt")],
        quiet=False,
    )
    say()
    if installed:
        ok("backend packages installed")
    else:
        fail("pip install failed — see the output above")

    # Only needed to run the test suite.
    run([str(venv_python()), "-m", "pip", "install", "mongomock_motor", "--quiet"])

    _report_optional_features()


def _report_optional_features() -> None:
    """Say which optional integrations are configured, and how to enable them.

    These are all genuinely optional — the app runs without any of them — but
    silence would leave someone wondering why the PDF upload box is greyed
    out.
    """
    env_file = BACKEND / ".env"
    env = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()

    checks = [
        ("AI features (roster summaries, PDF/photo import)",
         bool(env.get("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY"),
        ("Emailing rosters to staff",
         bool(env.get("RESEND_API_KEY")), "RESEND_API_KEY"),
        ("Google sign-in",
         bool(env.get("GOOGLE_CLIENT_ID")), "GOOGLE_CLIENT_ID"),
    ]
    missing = [(label, key) for label, configured, key in checks if not configured]
    if not missing:
        ok("all optional integrations configured")
        return

    warn("optional features not configured (the app still runs):")
    for label, key in missing:
        say(f"      {DIM}{label}{RESET}")
        say(f"        set {BOLD}{key}{RESET} in backend/.env")


# ---------------------------------------------------------------------------
# 4. Frontend
# ---------------------------------------------------------------------------
def install_frontend() -> None:
    header("4. Frontend dependencies")

    if (FRONTEND / "node_modules").exists():
        ok("node_modules already present (delete it to reinstall)")
        return

    manager = "yarn" if which("yarn") else "npm"
    say(f"  {DIM}running {manager} install — this is the slow one...{RESET}")
    if run([manager, "install"], cwd=FRONTEND):
        ok(f"{manager} install complete")
    else:
        fail(f"{manager} install failed — run it manually in frontend/")


# ---------------------------------------------------------------------------
# 5. MongoDB
# ---------------------------------------------------------------------------
def check_mongo() -> None:
    header("5. MongoDB")

    env: dict[str, str] = {}
    for line in (BACKEND / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()

    url = env.get("MONGO_URL", "")
    if not url:
        fail("MONGO_URL is not set in backend/.env")
        return

    probe = (
        "import sys;"
        "from pymongo import MongoClient;"
        f"MongoClient({url!r}, serverSelectionTimeoutMS=4000).admin.command('ping')"
    )
    if run([str(venv_python()), "-c", probe]):
        ok(f"connected to MongoDB ({url.split('@')[-1][:48]})")
        return

    fail("could not reach MongoDB")
    say()
    say(f"  {BOLD}Pick whichever is easiest:{RESET}")
    say(f"  {DIM}Docker (fastest if you have it):{RESET}")
    say("      docker run -d -p 27017:27017 --name roster-mongo mongo:7")
    say(f"  {DIM}MongoDB Atlas (free, nothing to install):{RESET}")
    say("      https://www.mongodb.com/cloud/atlas — create a free cluster,")
    say("      then paste its connection string into MONGO_URL in backend/.env")
    say(f"  {DIM}Local install:{RESET}")
    say("      https://www.mongodb.com/try/download/community")


# ---------------------------------------------------------------------------
# 6. Next steps
# ---------------------------------------------------------------------------
def print_next_steps() -> None:
    activate = (
        r".\venv\Scripts\Activate.ps1" if IS_WINDOWS else "source venv/bin/activate"
    )
    runner = "yarn" if which("yarn") else "npm run"

    if problems:
        header(f"{RED}Setup incomplete{RESET}")
        for item in problems:
            say(f"  - {item}")
        say(f"\nFix the above, then run {BOLD}python bootstrap.py{RESET} again.")
        return

    header(f"{GREEN}Ready.{RESET} Open two terminals:")
    say()
    say(f"  {BOLD}Terminal 1 — backend{RESET}")
    say(f"      cd backend")
    say(f"      {activate}")
    say(f"      uvicorn app.main:app --reload --port 8001")
    say()
    say(f"  {BOLD}Terminal 2 — frontend{RESET}")
    say(f"      cd frontend")
    say(f"      {runner} start")
    say()
    say(f"  Then open {BOLD}http://localhost:3000{RESET} and create an account.")
    say(f"  API docs: {DIM}http://localhost:8001/docs{RESET}")
    say()
    say(f"  {BOLD}Load your real roster history:{RESET}")
    say(f"      cd backend && {activate}")
    say(f'      python ml/import_workbook.py "path/to/roster.xlsx" --email you@example.com')
    say()
    say(f"  {BOLD}Run the tests:{RESET}  cd backend && pytest")


def main() -> None:
    say(f"{BOLD}Roster — local setup{RESET}")
    check_prerequisites()
    if any("Python" in p for p in problems):
        print_next_steps()
        return
    write_env_files()
    install_backend()
    install_frontend()
    check_mongo()
    print_next_steps()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Ctrl+C during a long pip install is common. Exit cleanly with a
        # useful next step rather than dumping a traceback that looks like a
        # crash in the script itself.
        say(f"\n\n{YELLOW}Interrupted.{RESET} Nothing was broken — re-run "
            f"{BOLD}python bootstrap.py{RESET} to pick up where it left off.")
        say(f"{DIM}Installs are resumable; pip skips whatever is already there.{RESET}")
        sys.exit(130)

        