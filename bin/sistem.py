"""The Sunucu odası: this computer's status (GET /api/sistem) and the live check of the projects' own domains.

Computer status — read-only, the standard library and macOS's own commands only (`sysctl`, `vm_stat`,
`memory_pressure` when present, `ps -axo pid,pcpu,rss,comm`, `df -k /`, `pmset -g batt`; Docker only when `docker` is
on PATH and its daemon answers `docker stats --no-stream` with numbers). Every call has a timeout of at most
TIMEOUT_SN and no shell; a sample is cached for CACHE_SN.

Privacy (hard rule, owner decision 2026-11-12): processes are grouped only by the base name of the executable (`comm`); the
page gets group totals only (count, %CPU, memory) — never a command line, a path, a project, container or user name,
never the base names inside a group. A process whose `comm` reaches a forbidden project, the vault's credential notes or the private
folders (bin/adimlar.py `forbidden`, the guard's patterns) is not counted at all, and `temizle` drops every string of
the output that matches those patterns as a last filter.

Suggestions are rule-based text only: the office never closes, kills or deletes anything; the decision is the owner's.

Domains — `ofis.json` → `projects.<P>.sistem: {domainler: [...], eposta_domaini: "...", cloudflare: true|false}`
(optional; no project has it until the owner gives the list). DomainKontrol runs a few times a day in its own server thread
and contacts only those domains: HTTPS (a HEAD request: the status code and the days until the TLS certificate
expires), DNS (the A records and whether they are in Cloudflare's published ranges) and MX (with `dig` when installed,
else "bilinmiyor"). No API keys. The result is cached in durum/sistem/domainler.json; a problem (a site that does not
open, a certificate with fewer than SERTIFIKA_GUN days, a DNS change) sends the CEO one `[Ofis · sistem]` notice,
once per problem until it changes.
"""
import hashlib
import http.client
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from urllib.parse import urlsplit

import adimlar
import sahip

TIMEOUT_SN = 3
CACHE_SN = 20
GECMIS = 3  # samples kept for the "sustained high CPU" rule
YUKSEK_CPU = 150.0  # %CPU of one group, sustained over GECMIS samples
TARAYICI_CPU = 100.0  # a browser using more than one core while the office page is open
BOSTA_CPU = 1.0  # a Claude process under this %CPU is idle
COK_BOSTA_CLAUDE = 6
DOCKER_BOSTA_MB = 1024  # Docker holding at least this much memory …
DOCKER_BOSTA_CPU = 2.0  # … while its containers use less than this %CPU
DISK_ESIK = 90
BELLEK_BOS_ESIK = 10  # memory_pressure's free percentage under this: memory is tight
SARI, KIRMIZI = 0.7, 1.0  # load average (1 min) per core

GRUPLAR = ("Java", "Node", "Python", "Docker", "Tarayıcılar", "Claude oturumları", "Codex/OpenCode", "Ofis sunucusu",
           "Diğer")
TARAYICI = re.compile(r"^(?:google chrome|chromium|chrome|brave browser|safari|firefox|microsoft edge|"
                      r"com\.apple\.webkit\.|com\.apple\.safari|safariplatformsupport|plugin-container)", re.I)
PYTHON = re.compile(r"^python(?:\d+(?:\.\d+)*)?$", re.I)
# Docker Desktop, Colima / Lima and OrbStack (the docker CLI may talk to any of them)
DOCKER = re.compile(r"^(?:com\.docker\.|docker|vpnkit|colima|limactl|orbstack)", re.I)
# their virtual machines: counted as Docker only beside one of them (the Android emulator runs qemu-system too)
VM = re.compile(r"^(?:com\.apple\.virtualization\.virtualmachine$|qemu-system)", re.I)

YOK_METNI = "Domain listesi henüz yok — Ar-Ge ilk çalışmasında soracak"
DOMAIN_ARALIK_SN = 6 * 3600  # "a few times a day": four checks
SERTIFIKA_GUN = 14
AG_TIMEOUT_SN = 5
SYSTEM_PREFIX = "[Ofis · sistem]\n"
DOMAIN = re.compile(r"(?=.{1,253}$)(?:(?!-)[a-z0-9-]{1,63}(?<!-)\.)+[a-z]{2,63}")
# Cloudflare's published IPv4 ranges (source: https://www.cloudflare.com/ips-v4, as of 2026-11). Kept in code: no
# request is made to fetch them.
CLOUDFLARE_V4 = tuple(ipaddress.ip_network(n) for n in (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18", "108.162.192.0/18",
    "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22"))


# --- commands ---

def calistir(argv, timeout=TIMEOUT_SN):
    """stdout of one command (argument list, no shell, no stdin), at most TIMEOUT_SN seconds; raises on failure."""
    r = subprocess.run(argv, capture_output=True, text=True, timeout=min(float(timeout), TIMEOUT_SN),
                       stdin=subprocess.DEVNULL, check=False)
    if r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, argv[0])
    return r.stdout


def _num(text, cast=float):
    try:
        return cast(text)
    except (TypeError, ValueError):
        return None


# --- parsers (never raise on garbage) ---

def parse_sysctl(text):
    """`sysctl hw.ncpu hw.memsize vm.loadavg kern.boottime kern.memorystatus_vm_pressure_level` → numbers."""
    vals = {}
    for line in (text or "").splitlines():
        k, sep, v = line.partition(":")
        if sep:
            vals[k.strip()] = v.strip()
    yuk = [x for x in (_num(p) for p in re.findall(r"[\d.]+", vals.get("vm.loadavg", ""))[:3]) if x is not None]
    boot = re.search(r"sec\s*=\s*(\d+)", vals.get("kern.boottime", ""))
    return {"cekirdek": _num(vals.get("hw.ncpu"), int), "bellek_bayt": _num(vals.get("hw.memsize"), int),
            "yuk": yuk if len(yuk) == 3 else None, "acilis": int(boot.group(1)) if boot else None,
            "baski": _num(vals.get("kern.memorystatus_vm_pressure_level"), int)}


def parse_vm_stat(text):
    """`vm_stat` → {sayfa, kullanilan_bayt}: app memory (anonymous − purgeable) + wired + compressed (Activity
    Monitor's "Memory Used"); active pages stand in for the app memory on an older macOS."""
    m = re.search(r"page size of (\d+) bytes", text or "")
    sayfa = int(m.group(1)) if m else None
    p = {}
    for line in (text or "").splitlines():
        k, sep, v = line.partition(":")
        n = _num(v.strip().rstrip("."), int) if sep else None
        if n is not None:
            p[k.strip().strip('"')] = n
    if not sayfa:
        return {"sayfa": None, "kullanilan_bayt": None}
    app = p["Anonymous pages"] - p.get("Pages purgeable", 0) if "Anonymous pages" in p else p.get("Pages active")
    parts = (app, p.get("Pages wired down"), p.get("Pages occupied by compressor"))
    if any(x is None for x in parts):
        return {"sayfa": sayfa, "kullanilan_bayt": None}
    return {"sayfa": sayfa, "kullanilan_bayt": sum(parts) * sayfa}


def parse_memory_pressure(text):
    m = re.search(r"free percentage:\s*(\d+)%", text or "")
    return int(m.group(1)) if m else None


def parse_df(text):
    """`df -k /` → {toplam_gb, bos_gb, dolu_yuzde}. On APFS "Used" of / is the system volume only, so the fullness is
    the container's: size − available."""
    lines = (text or "").splitlines()
    for line in lines[1:]:
        f = line.split()
        if len(f) >= 4:
            size, avail = _num(f[1], int), _num(f[3], int)
            if size and avail is not None:
                return {"toplam_gb": round(size / 1048576, 1), "bos_gb": round(avail / 1048576, 1),
                        "dolu_yuzde": round(100 * (size - avail) / size)}
    return None


def parse_pmset(text):
    """`pmset -g batt` → {yuzde, durum, kaynak} or None (no battery)."""
    m = re.search(r"InternalBattery[^\t]*\t\s*(\d+)%;\s*([a-zA-Z ]+);", text or "")
    if not m:
        return None
    state = m.group(2).strip().lower()
    durum = {"charging": "şarj oluyor", "discharging": "pilde", "charged": "dolu", "finishing charge": "şarj oluyor",
             "ac attached": "adaptörde"}.get(state, "bilinmiyor")
    kaynak = "adaptör" if "AC Power" in (text or "") else "pil" if "Battery Power" in (text or "") else None
    return {"yuzde": int(m.group(1)), "durum": durum, "kaynak": kaynak}


UNITS = {"b": 1 / 1048576, "kib": 1 / 1024, "kb": 1 / 1024, "mib": 1, "mb": 1, "gib": 1024, "gb": 1024,
         "tib": 1048576, "tb": 1048576}


def parse_docker(text):
    """`docker stats --no-stream --format '{{.CPUPerc}}\\t{{.MemUsage}}'` → {konteyner, cpu, bellek_mb}: numbers
    only (the format asks for no name or id)."""
    n, cpu, mem = 0, 0.0, 0.0
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        c = _num(parts[0].strip().rstrip("%"))
        m = re.match(r"\s*([\d.]+)\s*([A-Za-z]+)", parts[1])
        if c is None or not m or m.group(2).lower() not in UNITS:
            continue
        n += 1
        cpu += c
        mem += float(m.group(1)) * UNITS[m.group(2).lower()]
    return {"konteyner": n, "cpu": round(cpu, 2), "bellek_mb": round(mem)}


PS_LINE = re.compile(r"^\s*(\d+)\s+([\d.]+)\s+(\d+)\s+(.+?)\s*$")


def parse_ps(text):
    """`ps -axo pid,pcpu,rss,comm` → [{pid, cpu, rss_kb, comm}] (comm may hold spaces; it stays in this module)."""
    out = []
    for line in (text or "").splitlines()[1:]:
        m = PS_LINE.match(line)
        if m:
            out.append({"pid": int(m.group(1)), "cpu": float(m.group(2)), "rss_kb": int(m.group(3)),
                        "comm": m.group(4)})
    return out


def grup_adi(base, docker_var):
    """The group of one executable's base name."""
    low = base.casefold()
    first = low.split(" ", 1)[0]
    if first == "java":
        return "Java"
    if first in ("node", "npm", "npx"):
        return "Node"
    if PYTHON.match(first) or low == "python":
        return "Python"
    if base == "claude":  # the CLI only, lower case (the desktop app "Claude" / "Claude Helper …" is no session)
        return "Claude oturumları"
    if first in ("codex", "opencode") or first.startswith(("codex-", "opencode-")):
        return "Codex/OpenCode"
    if DOCKER.match(low) or (VM.match(low) and docker_var):
        return "Docker"
    if TARAYICI.match(low):
        return "Tarayıcılar"
    return "Diğer"


def gruplar(procs, own_pid):
    """Group totals [{ad, sayi, cpu, bellek_mb[, bosta]}] in GRUPLAR order (only non-empty groups). Grouped by the base
    name only; a process whose comm reaches a forbidden project or the private notes is not counted."""
    kept = [p for p in procs if not adimlar.forbidden(p["comm"])]
    bases = {p["pid"]: os.path.basename(p["comm"].rstrip("/")) or p["comm"] for p in kept}
    docker_var = any(DOCKER.match(b.casefold()) for b in bases.values())
    acc = {}
    for p in kept:
        ad = "Ofis sunucusu" if p["pid"] == own_pid else grup_adi(bases[p["pid"]], docker_var)
        g = acc.setdefault(ad, {"ad": ad, "sayi": 0, "cpu": 0.0, "kb": 0, "bosta": 0})
        g["sayi"] += 1
        g["cpu"] += p["cpu"]
        g["kb"] += p["rss_kb"]
        g["bosta"] += p["cpu"] < BOSTA_CPU
    out = []
    for ad in GRUPLAR:
        g = acc.get(ad)
        if not g:
            continue
        row = {"ad": ad, "sayi": g["sayi"], "cpu": round(g["cpu"], 1), "bellek_mb": round(g["kb"] / 1024)}
        if ad == "Claude oturumları":
            row["bosta"] = g["bosta"]
        out.append(row)
    return out


def temizle(value):
    """The last filter: every string (and dict key) that reaches a forbidden project, the credential notes or the private folders is
    dropped, wherever it is in the output."""
    if isinstance(value, dict):
        return {k: temizle(v) for k, v in value.items()
                if not (isinstance(k, str) and adimlar.forbidden(k)) and not (isinstance(v, str) and adimlar.forbidden(v))}
    if isinstance(value, list):
        return [temizle(v) for v in value if not (isinstance(v, str) and adimlar.forbidden(v))]
    return value


def seviye(cpu, bellek):
    """'yesil' / 'sari' / 'kirmizi' from the 1-minute load per core and the kernel's memory pressure level."""
    rank = 0
    oran = cpu.get("yuk_orani") if cpu else None
    if oran is not None:
        rank = 2 if oran >= KIRMIZI else 1 if oran >= SARI else 0
    b = (bellek or {}).get("baski")
    rank = max(rank, 2 if b == "kritik" else 1 if b == "uyari" else 0)
    return ("yesil", "sari", "kirmizi")[rank] if (oran is not None or b) else None


def _gb(mb):
    return f"{mb / 1024:.1f}".replace(".", ",") + " GB"


def oneriler(s, gecmis, sayfa_acik):
    """Rule-based suggestions (text only; the office never acts on them). s: one sample, gecmis: the last samples'
    {group: cpu} maps (oldest first, s included)."""
    out = []
    g = {x["ad"]: x for x in s.get("gruplar") or []}
    dk = g.get("Docker")
    d = s.get("docker")
    if dk and dk["bellek_mb"] >= DOCKER_BOSTA_MB and (d is None or d["cpu"] < DOCKER_BOSTA_CPU) and \
            dk["cpu"] < 5 * DOCKER_BOSTA_CPU:
        what = "hiç konteyner çalışmıyor" if not d or not d["konteyner"] else f"{d['konteyner']} konteyner boşta"
        out.append({"tur": "docker-bosta", "metin": f"Docker {_gb(dk['bellek_mb'])} bellek tutuyor ama {what}. "
                    f"Kullanmıyorsan Docker Desktop'ı kapatmak belleği rahatlatır (karar {sahip.in_()})."})
    cl = g.get("Claude oturumları")
    if cl and cl.get("bosta", 0) >= COK_BOSTA_CLAUDE:
        out.append({"tur": "claude-bosta", "metin": f"{cl['bosta']} Claude oturumu boşta duruyor "
                    f"({_gb(cl['bellek_mb'])} bellek). İşi biten oturumları kapatmayı düşünebilirsin (karar {sahip.in_()})."})
    disk = s.get("disk")
    if disk and disk["dolu_yuzde"] > DISK_ESIK:
        out.append({"tur": "disk", "metin": f"Disk %{disk['dolu_yuzde']} dolu ({_gb(disk['bos_gb'] * 1024)} boş). "
                    f"Gereksiz büyük dosyaları temizlemeyi düşünebilirsin (karar {sahip.in_()})."})
    b = s.get("bellek") or {}
    if b.get("baski") in ("uyari", "kritik") or (b.get("bos_yuzde") is not None and b["bos_yuzde"] < BELLEK_BOS_ESIK):
        out.append({"tur": "bellek", "metin": "Bellek sıkışık (macOS bellek baskısı "
                    f"{'kritik' if b.get('baski') == 'kritik' else 'yüksek'}). En çok bellek tutan grubu kapatmak "
                    f"bilgisayarı rahatlatır (karar {sahip.in_()})."})
    if len(gecmis) >= GECMIS:
        for ad in GRUPLAR:
            if all(h.get(ad, 0) > YUKSEK_CPU for h in list(gecmis)[-GECMIS:]):
                out.append({"tur": "cpu-yuksek", "metin": f"{ad} bir süredir %{round(g.get(ad, {}).get('cpu', 0))} "
                            f"işlemci kullanıyor. Gerekmiyorsa kapatmayı düşünebilirsin (karar {sahip.in_()})."})
    tr = g.get("Tarayıcılar")
    if sayfa_acik and tr and tr["cpu"] > TARAYICI_CPU:
        out.append({"tur": "tarayici", "metin": f"Tarayıcılar %{round(tr['cpu'])} işlemci kullanıyor ve ofis sayfası "
                    "açık. Sayfayı ?hafif=1 ile açmak bilgisayarı serinletir."})
    return out


class Sistem:
    """Samples the computer (cached CACHE_SN), keeps the last GECMIS group CPU maps for the sustained-CPU rule.
    `durum()` is the /api/sistem body, `ozet()` the scene's small summary from the cache (never a command)."""

    def __init__(self, run=calistir, now=time.time, which=shutil.which, own_pid=None, durum_dir=None, cfg=None):
        self.run_cmd = run
        self.now = now
        self.which = which
        self.own_pid = os.getpid() if own_pid is None else own_pid
        self.durum_dir = durum_dir
        self.cfg = cfg  # a callable returning ofis.json (the domain section), or None
        self.lock = threading.Lock()  # one sample at a time (the commands run under it)
        self._veri = threading.Lock()  # the cached sample: ozet() never waits for a sample being taken
        self._son = None  # the last sample (group totals and numbers only)
        self._zaman = None
        self._gecmis = deque(maxlen=GECMIS)
        self._sayfa_acik = False

    def _cmd(self, argv):
        if not self.which(argv[0]):
            return None
        try:
            return self.run_cmd([self.which(argv[0])] + argv[1:], TIMEOUT_SN)
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def _ornek(self):
        sc = parse_sysctl(self._cmd(["sysctl", "hw.ncpu", "hw.memsize", "vm.loadavg", "kern.boottime",
                                     "kern.memorystatus_vm_pressure_level"]) or "")
        vm = parse_vm_stat(self._cmd(["vm_stat"]) or "")
        bos = parse_memory_pressure(self._cmd(["memory_pressure"]) or "")
        df = parse_df(self._cmd(["df", "-k", "/"]) or "")
        pil = parse_pmset(self._cmd(["pmset", "-g", "batt"]) or "")
        ps = parse_ps(self._cmd(["ps", "-axo", "pid,pcpu,rss,comm"]) or "")
        docker = None
        out = self._cmd(["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}\t{{.MemUsage}}"])
        if out is not None:
            docker = parse_docker(out)
        now = self.now()
        cores = sc["cekirdek"]
        yuk = sc["yuk"]
        cpu = {"cekirdek": cores, "yuk": yuk,
               "yuk_orani": round(yuk[0] / cores, 2) if yuk and cores else None}
        toplam = sc["bellek_bayt"]
        kul = vm["kullanilan_bayt"]
        bellek = {"toplam_gb": round(toplam / 1073741824, 1) if toplam else None,
                  "kullanilan_gb": round(kul / 1073741824, 1) if kul is not None else None,
                  "yuzde": round(100 * kul / toplam) if kul is not None and toplam else None,
                  "baski": {1: "normal", 2: "uyari", 4: "kritik"}.get(sc["baski"]), "bos_yuzde": bos}
        sample = {"zaman": datetime.fromtimestamp(now).isoformat(timespec="seconds"), "cpu": cpu, "bellek": bellek,
                  "disk": df, "pil": pil, "acik_kalma_sn": int(now - sc["acilis"]) if sc["acilis"] else None,
                  "gruplar": gruplar(ps, self.own_pid), "docker": docker}
        sample["seviye"] = seviye(cpu, bellek)
        return sample

    def _taze(self, force=False):
        with self.lock:
            now = self.now()
            if force or self._son is None or self._zaman is None or now - self._zaman >= CACHE_SN:
                s = self._ornek()
                with self._veri:
                    self._gecmis.append({g["ad"]: g["cpu"] for g in s["gruplar"]})
                    self._son, self._zaman = s, now
            with self._veri:
                return self._son, list(self._gecmis)

    def durum(self, sayfa_acik=False, force=False):
        """The /api/sistem body: the last sample (fresh when older than CACHE_SN), its suggestions and the domains."""
        self._sayfa_acik = bool(sayfa_acik)
        s, gecmis = self._taze(force)
        out = dict(s, oneriler=oneriler(s, gecmis, sayfa_acik))
        out["domainler"] = domain_ozeti(self.durum_dir, self.cfg() if self.cfg else None) if self.durum_dir else None
        return temizle(out)

    def ozet(self):
        """{seviye, oneri, domain_sorunu} from the cached sample (no command, never waits for one being taken; None
        before the first sample)."""
        with self._veri:
            s, gecmis = self._son, list(self._gecmis)
        if s is None:
            return None
        return {"seviye": s.get("seviye"), "oneri": len(oneriler(s, gecmis, self._sayfa_acik)),
                "domain_sorunu": domain_sorunu(self.durum_dir) if self.durum_dir else 0}

    def run(self, stop_event, izleniyor=lambda: True, sayfa_acik=lambda: False, interval=CACHE_SN):
        """Samples every `interval` seconds while the page is watched (the sustained-CPU rule needs regular samples)."""
        while not stop_event.is_set():
            try:
                if izleniyor():
                    self._sayfa_acik = bool(sayfa_acik())
                    self._taze()
            except Exception as e:  # never stops the thread
                print(f"ofis: sistem örneği alınamadı: {type(e).__name__}", file=sys.stderr)
            stop_event.wait(interval)


# --- domains ---

def cloudflare_mi(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in n for n in CLOUDFLARE_V4)


def domain_temiz(value):
    """A lower-case host name from a domain or URL entry, or None (invalid, or reaching a forbidden project / the private notes)."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if "://" in v:
        try:
            v = urlsplit(v).hostname or ""
        except ValueError:
            return None
    v = v.rstrip(".")
    if not DOMAIN.fullmatch(v) or adimlar.forbidden(v):
        return None
    return v


def https_kontrol(domain, timeout=AG_TIMEOUT_SN):
    """A HEAD request to https://<domain>/ → {acildi, durum_kodu, gun, bitis, hata}. 5xx or no answer: not open.
    The name is resolved first with a timeout (the connection's own timeout does not cover the lookup)."""
    if not dns_kontrol(domain, timeout):
        return {"acildi": False, "durum_kodu": None, "gun": None, "bitis": None, "hata": "adres çözülemedi"}
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection(domain, 443, timeout=timeout, context=ctx)
    try:
        conn.request("HEAD", "/", headers={"User-Agent": "Ofis-sunucu-odasi"})
        cert = conn.sock.getpeercert() if conn.sock else None
        code = conn.getresponse().status
    except ssl.SSLCertVerificationError:
        return {"acildi": False, "durum_kodu": None, "gun": None, "bitis": None, "hata": "sertifika doğrulanamadı"}
    except (OSError, http.client.HTTPException) as e:
        return {"acildi": False, "durum_kodu": None, "gun": None, "bitis": None,
                "hata": "zaman aşımı" if isinstance(e, (socket.timeout, TimeoutError)) else "bağlanılamadı"}
    finally:
        conn.close()
    bitis = (cert or {}).get("notAfter")
    gun = None
    if bitis:
        try:
            gun = int((ssl.cert_time_to_seconds(bitis) - time.time()) // 86400)
        except ValueError:
            gun = None
    return {"acildi": code < 500, "durum_kodu": code, "gun": gun, "bitis": bitis, "hata": None}


def dns_kontrol(domain, timeout=AG_TIMEOUT_SN):
    """The A records (sorted); [] when the lookup fails or takes longer than `timeout` (getaddrinfo has no timeout of
    its own: it runs in a daemon thread that is left behind when it stalls)."""
    out = []

    def lookup():
        try:
            out.extend(i[4][0] for i in socket.getaddrinfo(domain, 443, socket.AF_INET, socket.SOCK_STREAM))
        except (OSError, UnicodeError):
            pass
    t = threading.Thread(target=lookup, daemon=True)
    t.start()
    t.join(timeout)
    return [] if t.is_alive() else sorted(set(out))


def mx_kontrol(domain, which=shutil.which):
    """MX host names with `dig` (None when dig is not installed or fails: "bilinmiyor")."""
    dig = which("dig")
    if not dig:
        return None
    try:
        r = subprocess.run([dig, "+short", "+time=2", "+tries=1", "MX", domain], capture_output=True, text=True,
                           timeout=AG_TIMEOUT_SN, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    hosts = []
    for line in r.stdout.splitlines():
        f = line.split()
        if len(f) == 2 and f[0].isdigit():
            h = domain_temiz(f[1])
            if h:
                hosts.append(h)
    return sorted(set(hosts))


def domain_listesi(cfg):
    """[(project, domain, cloudflare)] and [(project, e-mail domain)] from ofis.json's projects.<P>.sistem."""
    sites, mail = [], []
    projects = (cfg or {}).get("projects") if isinstance(cfg, dict) else None
    for p, spec in (projects or {}).items():
        s = spec.get("sistem") if isinstance(spec, dict) else None
        if not isinstance(s, dict) or adimlar.forbidden(str(p)):
            continue
        seen = set()
        for d in s.get("domainler") or []:
            h = domain_temiz(d)
            if h and h not in seen:
                seen.add(h)
                sites.append((p, h, s.get("cloudflare") is True))
        e = domain_temiz(s.get("eposta_domaini"))
        if e:
            mail.append((p, e))
    return sites, mail


def _cache_path(durum_dir):
    return os.path.join(durum_dir, "sistem", "domainler.json")


def _read_cache(durum_dir):
    try:
        with open(_cache_path(durum_dir), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_cache(durum_dir, data):
    path = _cache_path(durum_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


SORUN_METNI = {"acilmiyor": "açılmıyor", "sertifika": "sertifikası bitiyor", "dns": "DNS değişti"}


class DomainKontrol:
    """The domain loop. cfg: a callable returning ofis.json (read again every pass, so a list the CEO wrote is picked up);
    ceo: has enqueue(text, key). https/dns/mx: the network functions (fakes in tests)."""

    def __init__(self, cfg, durum_dir, ceo, https=https_kontrol, dns=dns_kontrol, mx=mx_kontrol, now=time.time,
                 log=None):
        self.cfg = cfg
        self.durum_dir = durum_dir
        self.ceo = ceo
        self.https, self.dns, self.mx = https, dns, mx
        self.now = now
        self.log = log or (lambda line: print(line, file=sys.stderr))

    def vakti_geldi(self):
        son = _read_cache(self.durum_dir).get("son_kontrol_epoch")
        return not isinstance(son, (int, float)) or self.now() - son >= DOMAIN_ARALIK_SN

    def _https(self, domain):
        try:
            r = self.https(domain)
        except Exception:  # a fake or a library error: the site did not open
            r = None
        if not isinstance(r, dict):
            return {"acildi": False, "durum_kodu": None, "gun": None, "bitis": None, "hata": "bağlanılamadı"}
        return {"acildi": bool(r.get("acildi")), "durum_kodu": r.get("durum_kodu"), "gun": r.get("gun"),
                "bitis": r.get("bitis"), "hata": r.get("hata")}

    def kontrol_et(self):
        """One pass over every registered domain. False (and nothing contacted) when no project has a list."""
        sites, mail = domain_listesi(self.cfg())
        if not sites and not mail:
            if _read_cache(self.durum_dir).get("domainler"):  # the list was emptied: no stale problem stays lit
                _write_cache(self.durum_dir, {"son_kontrol": None, "domainler": {}, "eposta": {}})
            return False
        old = _read_cache(self.durum_dir)
        old_rows = old.get("domainler") if isinstance(old.get("domainler"), dict) else {}
        now = self.now()
        stamp = datetime.fromtimestamp(now).isoformat(timespec="seconds")
        rows, notices = {}, []
        for proje, domain, cf_expected in sites:
            prev = old_rows.get(domain) if isinstance(old_rows.get(domain), dict) else {}
            h = self._https(domain)
            try:
                ips = sorted(set(self.dns(domain) or []))
            except Exception:
                ips = []
            prev_ips = prev.get("ipler") if isinstance(prev.get("ipler"), list) else []
            cf = bool(ips) and all(cloudflare_mi(i) for i in ips)
            # a change: the new addresses share none with the previous ones (a CDN or load balancer rotating within its
            # pool keeps some), and it is not Cloudflare moving between its own addresses
            degisti = bool(ips) and bool(prev_ips) and not set(ips) & set(prev_ips) and \
                not (cf and all(cloudflare_mi(i) for i in prev_ips))
            current = {}
            if not h["acildi"]:
                current["acilmiyor"] = h["hata"] or (f"durum kodu {h['durum_kodu']}" if h["durum_kodu"] else "")
            if isinstance(h["gun"], int) and h["gun"] < SERTIFIKA_GUN:
                current["sertifika"] = h["gun"]
            if degisti:
                current["dns"] = ",".join(ips)
            old_p = prev.get("sorunlar") if isinstance(prev.get("sorunlar"), dict) else {}
            sorunlar = {}
            for kind, detail in current.items():
                ident = {"acilmiyor": "", "sertifika": h["bitis"] or "", "dns": current.get("dns", "")}[kind]
                p = old_p.get(kind) if isinstance(old_p.get(kind), dict) else None
                if p and p.get("kimlik") == ident:
                    sorunlar[kind] = dict(p, detay=detail, son=stamp)
                    if not p.get("bildirildi") and p.get("anahtar"):  # its notice never reached the queue: again
                        notices.append((domain, kind, p["anahtar"], p.get("metin") or
                                        self._metin(proje, domain, kind, detail, prev_ips)))
                    continue
                key = "sistem-domain:" + hashlib.sha256(f"{domain}|{kind}|{ident}|{stamp}".encode()).hexdigest()[:20]
                text = self._metin(proje, domain, kind, detail, prev_ips)
                sorunlar[kind] = {"kimlik": ident, "detay": detail, "ilk": stamp, "son": stamp, "anahtar": key,
                                  "metin": text, "bildirildi": False}
                notices.append((domain, kind, key, text))
            rows[domain] = {"proje": proje, "https": {k: h[k] for k in ("acildi", "durum_kodu", "gun", "hata")},
                            # a failed lookup keeps the addresses of the last good one (the reference for a change)
                            "ipler": ips or prev_ips, "dns_bulundu": bool(ips), "cloudflare": cf,
                            "cloudflare_bekleniyor": cf_expected, "dns_degisti": degisti, "sorunlar": sorunlar,
                            "kontrol": stamp}
        mx_rows = {}
        for proje, domain in mail:
            try:
                hosts = self.mx(domain)
            except Exception:
                hosts = None
            mx_rows[domain] = {"proje": proje, "mx": hosts if isinstance(hosts, list) else None, "kontrol": stamp}
        # the notices first (a repeated key is a "duplicate" for the channel), then the cache records which went out
        for domain, kind, key, text in notices:
            try:
                self.ceo.enqueue(text, key)
                rows[domain]["sorunlar"][kind]["bildirildi"] = True
            except Exception as e:  # tried again on the next pass; the card still shows the problem
                self.log(f"ofis: domain bildirimi kuyruğa alınamadı: {type(e).__name__}")
        _write_cache(self.durum_dir, {"son_kontrol": stamp, "son_kontrol_epoch": now, "domainler": rows,
                                      "eposta": mx_rows})
        return True

    @staticmethod
    def _metin(proje, domain, kind, detail, prev_ips):
        if kind == "acilmiyor":
            what = f"{domain} açılmıyor ({detail})" if detail else f"{domain} açılmıyor"
        elif kind == "sertifika":
            what = f"{domain} sertifikası {detail} gün içinde bitiyor" if detail >= 0 else f"{domain} sertifikası bitmiş"
        else:
            was = ", ".join(prev_ips) or "—"
            what = f"{domain} DNS değişti: {was} → {detail.replace(',', ', ')}"
        return (f"{SYSTEM_PREFIX}Sunucu odası ({proje}): {what}. {sahip.e()} tek satırla söyle; ofis hiçbir şeyi "
                f"değiştirmez, karar {sahip.in_()}.")

    def run(self, stop_event, interval=600):
        """Checks when the last pass is older than DOMAIN_ARALIK_SN (looked at every `interval` seconds)."""
        while not stop_event.is_set():
            try:
                if self.vakti_geldi():
                    self.kontrol_et()
            except Exception as e:  # never stops the thread
                self.log(f"ofis: domain kontrolü yapılamadı: {type(e).__name__}: {e}")
            stop_event.wait(interval)


def domain_sorunu(durum_dir):
    """The number of open domain problems in the cache (the scene's warning light; no config read, no network)."""
    rows = _read_cache(durum_dir).get("domainler")
    if not isinstance(rows, dict):
        return 0
    return sum(len(r.get("sorunlar") or {}) for r in rows.values() if isinstance(r, dict))


def domain_ozeti(durum_dir, cfg):
    """The card's domain section: the configured domains with their last check (from the cache). No list: liste_var
    False and YOK_METNI."""
    sites, mail = domain_listesi(cfg)
    if not sites and not mail:
        return {"liste_var": False, "metin": YOK_METNI, "domainler": [], "eposta": [], "sorun_sayisi": 0,
                "son_kontrol": None}
    cache = _read_cache(durum_dir) if durum_dir else {}
    rows = cache.get("domainler") if isinstance(cache.get("domainler"), dict) else {}
    mx = cache.get("eposta") if isinstance(cache.get("eposta"), dict) else {}
    out, sorun = [], 0
    for proje, domain, cf_expected in sites:
        r = rows.get(domain) if isinstance(rows.get(domain), dict) else None
        if r is None:
            out.append({"proje": proje, "domain": domain, "kontrol": None, "https": None, "dns": None, "sorunlar": []})
            continue
        kinds = [k for k in ("acilmiyor", "sertifika", "dns") if k in (r.get("sorunlar") or {})]
        sorun += len(kinds)
        out.append({"proje": proje, "domain": domain, "kontrol": r.get("kontrol"), "https": r.get("https"),
                    "dns": {"ipler": r.get("ipler") or [], "bulundu": r.get("dns_bulundu"),
                            "cloudflare": r.get("cloudflare"), "cloudflare_bekleniyor": cf_expected,
                            "degisti": r.get("dns_degisti")},
                    "sorunlar": [{"tur": k, "metin": SORUN_METNI[k]} for k in kinds]})
    eposta = []
    for proje, domain in mail:
        m = mx.get(domain) if isinstance(mx.get(domain), dict) else {}
        eposta.append({"proje": proje, "domain": domain,
                       "mx": m.get("mx") if isinstance(m.get("mx"), list) else "bilinmiyor"})
    return {"liste_var": True, "metin": "", "domainler": out, "eposta": eposta, "sorun_sayisi": sorun,
            "son_kontrol": cache.get("son_kontrol")}
