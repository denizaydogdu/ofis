"""Runs the whole test suite in parallel (stdlib only).

    python3 test/hepsi.py                 # everything (the default full run includes the slow tests)
    python3 test/hepsi.py --hizli         # skips the tests marked @yavas (test/yavas.py); OFIS_YAVAS=1 keeps them
    python3 test/hepsi.py test_npc web    # only the files whose name contains one of these words
    python3 test/hepsi.py -j 2 --sure 900 # 2 workers, a 900 s limit per job

Workers: min(4, cpu/2), each job under `nice -n 10` (the owner's Mac stays cool). The slow files (BOLUNEN) run as one job per
TestCase class. One line per job: name, OK/FAIL/TIMEOUT, seconds; the failing jobs' output at the end; exit code 1 on
any failure. Job times are kept in test/__pycache__/hepsi-sureler.json (git-ignored) so the longest jobs start first."""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

TEST = Path(__file__).resolve().parent
ROOT = TEST.parent
BOLUNEN = {"test_npc.py", "test_denetci.py", "test_web.py", "test_ofis_plani.py", "test_akis.py", "test_kontrol.py",
           "test_postoffice.py"}
SURELER = TEST / "__pycache__" / "hepsi-sureler.json"
LISTE = r"""
import sys, unittest
sys.path.insert(0, sys.argv[1]); sys.argv = sys.argv[:1]
m = __import__(MODUL)
seen = []
def walk(s):
    for t in s:
        if isinstance(t, unittest.TestSuite): walk(t)
        else:
            c = type(t).__name__
            if c not in seen: seen.append(c)
walk(unittest.defaultTestLoader.loadTestsFromModule(m))
print("\n".join(seen))
"""


def siniflar(dosya):
    """The TestCase classes of a file that hold tests (unittest's own loader, inheritance included)."""
    code = LISTE.replace("MODUL", repr(dosya[:-3]))
    p = subprocess.run([sys.executable, "-I", "-c", code, str(TEST)], cwd=ROOT, capture_output=True, text=True,
                       timeout=120)
    return [x for x in p.stdout.split() if x] if p.returncode == 0 else []


def isler(secim):
    dosyalar = sorted(p.name for p in TEST.glob("test_*.py"))
    if secim:
        dosyalar = [d for d in dosyalar if any(s in d for s in secim)]
    out = []
    for d in dosyalar:
        cls = siniflar(d) if d in BOLUNEN else []
        out += [(f"{d[:-3]}.{c}", d, c) for c in cls] or [(d[:-3], d, None)]
    return out


def calistir(is_, env, sure):
    ad, dosya, cls = is_
    argv = ["nice", "-n", "10", sys.executable, "-I", str(TEST / dosya)] + ([cls] if cls else [])
    t = time.monotonic()
    p = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         start_new_session=True)
    try:
        cikti, _ = p.communicate(timeout=sure)
        durum = "OK" if p.returncode == 0 else "FAIL"
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        cikti, _ = p.communicate()
        durum = "TIMEOUT"
    sn = time.monotonic() - t
    son = [x for x in cikti.strip().splitlines() if x.startswith(("OK", "FAILED"))]
    return ad, durum, sn, (son[-1] if son else ""), cikti


def main():
    ap = argparse.ArgumentParser(description="Runs every test file in parallel.")
    ap.add_argument("secim", nargs="*", help="only files whose name contains one of these words")
    ap.add_argument("--hizli", action="store_true", help="skip the tests marked @yavas (OFIS_YAVAS=1 keeps them)")
    ap.add_argument("-j", type=int, default=min(4, max(1, (os.cpu_count() or 2) // 2)), help="workers (default min(4, cpu/2))")
    ap.add_argument("--sure", type=float, default=900, help="seconds per job before it is killed (default 900)")
    a = ap.parse_args()
    env = dict(os.environ)
    if a.hizli:
        env["OFIS_HIZLI"] = "1"
    try:
        eski = json.loads(SURELER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        eski = {}
    t0 = time.monotonic()
    liste = isler(a.secim)
    liste.sort(key=lambda x: -eski.get(x[0], 30 if x[2] else 5))  # the longest first
    print(f"{len(liste)} jobs, {a.j} workers{' (hızlı)' if a.hizli else ''}", flush=True)
    sonuc = []
    with ThreadPoolExecutor(a.j) as ex:
        futs = [ex.submit(calistir, x, env, a.sure) for x in liste]
        try:
            for f in as_completed(futs):
                ad, durum, sn, son, cikti = f.result()
                sonuc.append((ad, durum, sn, cikti))
                print(f"{ad:58s} {durum:7s} {sn:6.1f}s  {son}", flush=True)
        except KeyboardInterrupt:
            for f in futs:
                f.cancel()
            raise
    kotu = [x for x in sonuc if x[1] != "OK"]
    for ad, durum, sn, cikti in kotu:
        print(f"\n===== {ad}: {durum} =====\n" + "\n".join(cikti.splitlines()[-60:]))
    try:
        SURELER.parent.mkdir(exist_ok=True)
        SURELER.write_text(json.dumps({**eski, **{x[0]: round(x[2], 1) for x in sonuc}}, indent=0), encoding="utf-8")
    except OSError:
        pass
    print(f"\n{len(sonuc) - len(kotu)}/{len(sonuc)} jobs OK · wall {time.monotonic() - t0:.0f}s · "
          f"job time {sum(x[2] for x in sonuc):.0f}s")
    return 1 if kotu else 0

if __name__ == "__main__":
    sys.exit(main())
