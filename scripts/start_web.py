#!/usr/bin/env python3
"""Запуск Web UI одной командой: API + фронт + браузер."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
SRC = ROOT / "src"
API_URL = "http://127.0.0.1:8000/api/health"
UI_URL = "http://127.0.0.1:5173"


def _python_exe() -> str:
    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.is_file():
        return str(venv_py)
    return sys.executable


def _log(msg: str) -> None:
    print(msg, flush=True)


def _npm_exe() -> str:
    for name in ("npm.cmd", "npm.exe", "npm"):
        path = shutil.which(name)
        if path:
            return path
    return ""


def _ensure_npm_deps() -> None:
    if (WEB / "node_modules").is_dir():
        return
    _log("Первый запуск: npm install (может занять 1–2 мин)...")
    npm = _npm_exe()
    if not npm:
        sys.exit("Ошибка: npm не найден. Установите Node.js: https://nodejs.org/")
    subprocess.run([npm, "install"], cwd=str(WEB), check=True, shell=sys.platform == "win32")


def _wait_http(url: str, timeout: float = 90.0, label: str = "") -> bool:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.75)
    if label:
        _log(f"Таймаут: {label} не ответил за {int(timeout)} с")
    return False


def _start_api() -> tuple[Optional[subprocess.Popen], bool]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC.resolve()) + os.pathsep + env.get("PYTHONPATH", "")

    if _wait_http(API_URL, timeout=2):
        _log("API уже работает на :8000")
        return None, True

    cmd = [_python_exe(), "-m", "legal_monitor", "serve", "--host", "127.0.0.1", "--port", "8000"]
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env)
    if _wait_http(API_URL, timeout=45, label="API"):
        _log("API готов.")
        return proc, True
    _log("Ошибка: API не запустился (порт 8000 занят или нет модуля legal_monitor).")
    if proc.poll() is None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            proc.terminate()
    return None, False


def _start_ui() -> tuple[Optional[subprocess.Popen], bool]:
    if _wait_http(UI_URL, timeout=2):
        _log("UI уже работает на :5173")
        return None, True

    npm = _npm_exe()
    if not npm:
        _log("Ошибка: npm не найден.")
        return None, False

    cmd = [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"]
    proc = subprocess.Popen(cmd, cwd=str(WEB), shell=sys.platform == "win32")

    if _wait_http(UI_URL, timeout=120, label="UI"):
        _log("UI готов.")
        return proc, True

    _log("Ошибка: фронт не запустился.")
    _log("  - установите Node.js: https://nodejs.org/")
    _log("  - выполните: cd web && npm install")
    _log("  - проверьте, свободен ли порт 5173")
    if proc.poll() is None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            proc.terminate()
    return None, False


def main() -> int:
    os.chdir(ROOT)
    _ensure_npm_deps()

    _log("")
    _log("=" * 52)
    _log("  Legal Monitor — Web UI")
    _log("=" * 52)
    _log(f"  UI:   {UI_URL}")
    _log("  Остановка: Ctrl+C")
    _log("=" * 52)
    _log("")

    api_proc, api_ok = _start_api()
    ui_proc, ui_ok = _start_ui()

    if not api_ok or not ui_ok:
        return 1

    webbrowser.open(UI_URL)
    _log(f"Браузер: {UI_URL}")
    _log("")
    _log("Не закрывайте это окно — здесь работают серверы.")
    _log("Ctrl+C для остановки.")

    procs = [p for p in (api_proc, ui_proc) if p is not None]

    def shutdown(*_args) -> None:
        _log("\nОстановка...")
        for p in procs:
            if p.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    if not procs:
        _log("Серверы уже были запущены — окно можно закрыть или нажать Ctrl+C.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            shutdown()
        return 0

    try:
        while True:
            for p in procs:
                if p.poll() is not None:
                    _log(f"Сервер завершился (код {p.returncode}). Остановка...")
                    shutdown()
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
