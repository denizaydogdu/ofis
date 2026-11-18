#!/usr/bin/env python3
"""Start the office server at login (phase 6): a macOS LaunchAgent.

    python3 bin/autostart.py install [--dry-run]     # write ~/Library/LaunchAgents/local.ofis.server.plist, load it
    python3 bin/autostart.py uninstall [--dry-run]   # unload it and remove only our plist (the log stays)
    python3 bin/autostart.py status                  # installed? loaded? pid, port, a vault access error

The plist runs the python that ran `install` (sys.executable, absolute) with the absolute bin/server.py, in this
repository, at login (RunAtLoad). KeepAlive {SuccessfulExit: false} with ThrottleInterval restarts the server after a
crash (non-zero exit) but not after a clean exit; a second server exits 0 ("Ofis server already running"), so a
server already started by hand is never fought over. stdout and stderr go to one log file (~/Library/Logs/ofis/
server.log) so `status` can read the lines of the latest start in order. launchd gives a bare environment: PATH is
built at install time — the folders of `claude` (required: install refuses without it) and `codex` (optional: the
review falls back to Claude), of this python, then the PATH of the installing shell (Kontrol commands need the
project tools) and the system folders — plus HOME and LANG. Run `install` again after moving claude/codex or
changing PATH; it replaces our own plist (recognised by the OFIS_AUTOSTART marker) and refuses any other file with
the same name.
macOS privacy (TCC) may refuse ~/Documents (the Obsidian vault) to a launchd-started python: the server then logs one
Turkish error line starting with VAULT_ERROR, which `status` shows; the fix is to grant that python binary Full Disk
Access (System Settings > Privacy & Security), see CLAUDE.md.
Standard library only (plistlib); every path and the launchctl binary can be overridden for tests.
"""
import argparse
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABEL = "local.ofis.server"
MARKER = "OFIS_AUTOSTART"  # in EnvironmentVariables: our own plist
THROTTLE = 30  # seconds between restarts after a crash
AGENTS_DIR = os.path.expanduser("~/Library/LaunchAgents")
LOG_DIR = os.path.expanduser("~/Library/Logs/ofis")
LOG_NAME = "server.log"
SYSTEM_PATH = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")
START_MARKER = "ofis: başlatılıyor"  # server.main prints it first: the log lines after the last one are the latest start
VAULT_ERROR = "ofis: HATA Obsidian"  # server.vault_problem's line starts with it
PORT_LINE = re.compile(r"Ofis: http://127\.0\.0\.1:(\d+)")
LOG_TAIL = 256 * 1024
TIMEOUT = 30


class Refused(Exception):
    """Shown to the user (Turkish)."""


def build_path(which=shutil.which, python=sys.executable, current_path=None):
    """(PATH, claude, codex): claude's and codex's folders first, then this python's, the installing shell's PATH and
    the system folders, each once. Raises Refused when claude is not found."""
    claude = which("claude")
    if not claude:
        raise Refused("claude bulunamadı (PATH'te yok). Otomatik başlatma kurulmadı: sunucu claude olmadan iş "
                      "başlatamaz. claude'un çalıştığı bir terminalden yeniden deneyin.")
    codex = which("codex")
    folders = [os.path.dirname(claude)]
    if codex:
        folders.append(os.path.dirname(codex))
    folders.append(os.path.dirname(python))
    current = os.environ.get("PATH", "") if current_path is None else current_path
    folders += current.split(":") + list(SYSTEM_PATH)
    out = []
    for f in folders:
        if f and os.path.isabs(f) and f not in out:
            out.append(f)
    return ":".join(out), claude, codex


def build_plist(python, root, log_file, path_env, home, lang):
    server = os.path.join(root, "bin", "server.py")
    return {"Label": LABEL, "ProgramArguments": [python, server], "WorkingDirectory": root,
            "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False}, "ThrottleInterval": THROTTLE,
            "StandardOutPath": log_file, "StandardErrorPath": log_file,
            "EnvironmentVariables": {"PATH": path_env, "HOME": home, "LANG": lang, MARKER: "1"}}


def plist_path(agents_dir):
    return os.path.join(agents_dir, f"{LABEL}.plist")


def read_plist(path):
    """The plist as a dict, or None when it cannot be read."""
    try:
        with open(path, "rb") as f:
            data = plistlib.load(f)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    return data if isinstance(data, dict) else None


def is_ours(path):
    data = read_plist(path)
    env = (data or {}).get("EnvironmentVariables")
    return bool(data) and data.get("Label") == LABEL and isinstance(env, dict) and env.get(MARKER) == "1"


def _write_plist(path, data):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            plistlib.dump(data, f)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class Launchctl:
    def __init__(self, binary, uid):
        self.binary = binary
        self.uid = uid

    @property
    def domain(self):
        return f"gui/{self.uid}"

    @property
    def service(self):
        return f"{self.domain}/{LABEL}"

    def run(self, *args):
        try:
            proc = subprocess.run([self.binary, *args], capture_output=True, text=True, timeout=TIMEOUT,
                                  stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            return 1, f"{type(e).__name__}: {e}"
        return proc.returncode, (proc.stdout + proc.stderr).strip()

    def loaded(self):
        code, text = self.run("print", self.service)
        return (text if code == 0 else None)


def install(paths, ctl, which, python, current_path, dry_run, out, sleep=time.sleep):
    target = plist_path(paths["agents"])
    if os.path.lexists(target) and not is_ours(target):
        raise Refused(f"{target} başka bir program tarafından yazılmış; üzerine yazılmadı. Bakıp kendiniz kaldırın.")
    path_env, claude, codex = build_path(which, python, current_path)
    log_file = os.path.join(paths["logs"], LOG_NAME)
    data = build_plist(python, ROOT, log_file, path_env, os.path.expanduser("~"),
                       os.environ.get("LANG") or "en_US.UTF-8")
    if not codex:
        out.write("Uyarı: codex bulunamadı; kod incelemeleri Claude ile yapılır.\n")
    if dry_run:
        out.write(plistlib.dumps(data).decode())
        out.write(f"\n(deneme) yazılacak: {target}\n(deneme) çalışacak: launchctl bootout {ctl.service} (yüklüyse); "
                  f"launchctl bootstrap {ctl.domain} {target}\n")
        return 0
    os.makedirs(paths["logs"], exist_ok=True)
    was_loaded = ctl.loaded() is not None
    _write_plist(target, data)
    if was_loaded:
        ctl.run("bootout", ctl.service)
    code, text = 1, ""
    for attempt in range(3):  # right after a bootout launchd may still answer "Input/output error"
        code, text = ctl.run("bootstrap", ctl.domain, target)
        if code == 0:
            break
        sleep(1 + attempt)
    if code != 0:
        raise Refused(f"plist yazıldı ({target}) ama launchctl yükleyemedi: {text}")
    out.write(f"Otomatik başlatma kuruldu: {target}\nclaude: {claude}\ncodex: {codex or 'yok'}\n"
              f"Günlük: {log_file}\nOturum açılışında sunucu kendiliğinden başlar. Elle açılmış bir sunucu "
              "çalışıyorsa yenisi kapanır (çakışma olmaz); durum için: python3 bin/autostart.py status\n")
    return 0


def uninstall(paths, ctl, dry_run, out):
    target = plist_path(paths["agents"])
    if not os.path.lexists(target):
        out.write("Otomatik başlatma kurulu değil.\n")
        return 0
    if not is_ours(target):
        raise Refused(f"{target} başka bir program tarafından yazılmış; kaldırılmadı.")
    if dry_run:
        out.write(f"(deneme) çalışacak: launchctl bootout {ctl.service}; silinecek: {target}\n")
        return 0
    code, text = ctl.run("bootout", ctl.service)
    os.unlink(target)
    note = "" if code == 0 else f" (launchctl: {text})"
    out.write(f"Otomatik başlatma kaldırıldı: {target}{note}\nÇalışan sunucu durduruldu; günlük duruyor: "
              f"{os.path.join(paths['logs'], LOG_NAME)}\n")
    return 0


def latest_start(log_file):
    """The log lines of the latest server start (after the last START_MARKER)."""
    try:
        with open(log_file, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - LOG_TAIL))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(START_MARKER)]
    return lines[starts[-1]:] if starts else lines


def status(paths, ctl, out):
    target = plist_path(paths["agents"])
    if not os.path.lexists(target):
        out.write("Otomatik başlatma: kurulu değil.\n")
    elif is_ours(target):
        out.write(f"Otomatik başlatma: kurulu ({target}).\n")
    else:
        out.write(f"Otomatik başlatma: {target} başka bir programa ait.\n")
    info = ctl.loaded()
    if info is None:
        out.write("launchd: yüklü değil.\n")
    else:
        state = re.search(r"^\s*state = (\S+)", info, re.M)
        pid = re.search(r"^\s*pid = (\d+)", info, re.M)
        last = re.search(r"^\s*last exit code = (.+)$", info, re.M)
        parts = [f"durum {state.group(1)}" if state else "durum bilinmiyor"]
        if pid:
            parts.append(f"pid {pid.group(1)}")
        if last:
            parts.append(f"son çıkış kodu {last.group(1).strip()}")
        out.write("launchd: yüklü, " + ", ".join(parts) + ".\n")
    log_file = os.path.join(paths["logs"], LOG_NAME)
    lines = latest_start(log_file)
    if lines is None:
        out.write(f"Günlük yok: {log_file}\n")
        return 0
    ports = [m.group(1) for m in (PORT_LINE.search(line) for line in lines) if m]
    out.write(f"Sayfa: http://127.0.0.1:{ports[-1]}\n" if ports else "Sayfa: son açılışta port yazılmamış.\n")
    if any("already running" in line for line in lines):
        out.write("Not: son açılışta başka bir Ofis sunucusu zaten çalışıyordu; bu yüzden yenisi kapandı.\n")
    errors = [line for line in lines if line.startswith(VAULT_ERROR)]
    out.write(f"Obsidian erişimi: {errors[-1]}\n" if errors else "Obsidian erişimi: son açılışta sorun yazılmamış.\n")
    return 0


def main(argv, agents_dir=None, log_dir=None, launchctl="/bin/launchctl", uid=None, which=shutil.which,
         current_path=None, out=None, err=None, sleep=time.sleep):
    out, err = out or sys.stdout, err or sys.stderr
    p = argparse.ArgumentParser(prog="autostart.py", description="Start the office server at login (macOS).")
    p.add_argument("komut", choices=("install", "uninstall", "status"))
    p.add_argument("--dry-run", action="store_true", help="print what would be done; change nothing")
    args = p.parse_args(argv[1:])
    paths = {"agents": agents_dir or AGENTS_DIR, "logs": log_dir or LOG_DIR}
    ctl = Launchctl(launchctl, os.getuid() if uid is None else uid)
    try:
        if args.komut == "install":
            return install(paths, ctl, which, sys.executable, current_path, args.dry_run, out, sleep)
        if args.komut == "uninstall":
            return uninstall(paths, ctl, args.dry_run, out)
        return status(paths, ctl, out)
    except Refused as e:
        err.write(f"REFUSED: {e}\n")
        return 1
    except OSError as e:
        err.write(f"REFUSED: {type(e).__name__}: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
