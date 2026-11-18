"""Tests for bin/sistem.py: the computer's status for the Sunucu odası (GET /api/sistem) and the domain check loop.

Every command and every network call is faked: no real `ps`, no real network. Run: python3 -I test/test_sistem.py"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import fakes  # noqa: E402,F401 (isolates the job lock)
import sistem  # noqa: E402

OWN_PID = 4242

SYSCTL = """hw.ncpu: 10
hw.memsize: 17179869184
vm.loadavg: { 4.50 5.17 5.07 }
kern.boottime: { sec = 1793703075, usec = 785448 } Tue Nov  3 13:51:15 2026
kern.memorystatus_vm_pressure_level: 1
"""
VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                     3973.
Pages active:                                 224539.
Pages inactive:                               223410.
Pages wired down:                             196230.
Pages purgeable:                                4033.
Anonymous pages:                              314853.
Pages occupied by compressor:                 360026.
"""
MEMORY_PRESSURE = "The system has 17179869184 (1048576 pages with a page size of 16384).\n" \
                  "System-wide memory free percentage: 44%\n"
DF = """Filesystem     1024-blocks      Used Available Capacity iused     ifree %iused  Mounted on
/dev/disk3s1s1   482797652  12277044  69822292    15%  458726 698222920    0%   /
"""
PMSET = """Now drawing from 'AC Power'
 -InternalBattery-0 (id=8912995)\t94%; charging; 0:33 remaining present: true
"""
# a ZIM-looking program, a project path, a user name in a path, a rewritten process title (postgres puts its user and
# database in it) and a container-looking name: none of them may ever leave the module
PS = f"""  PID  %CPU    RSS COMM
    1   0.5  11904 /sbin/launchd
  200  80.0 2097152 /Library/Java/JavaVirtualMachines/jdk-21.jdk/Contents/Home/bin/java
  201  20.0 1048576 /Users/kullanici7/Dev/zim/zim-server/bin/java
  202   1.0  204800 /Users/kullanici7/Dev/zim/runner
  203   3.0  102400 zim-agent
  210  10.0  512000 /opt/homebrew/bin/node
  211   0.0   51200 npm exec gizli-proje-mcp
  220   5.0  307200 /opt/homebrew/Cellar/python@3.13/3.13.1/Frameworks/Python.framework/Versions/3.13/bin/python3.13
  {OWN_PID}   2.0  102400 /opt/homebrew/bin/python3
  230  60.0 1048576 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
  231  50.0  524288 /Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Helpers/Google Chrome Helper (Renderer).app/Contents/MacOS/Google Chrome Helper (Renderer)
  232   1.0  102400 /Applications/Safari.app/Contents/MacOS/Safari
  233   0.5   51200 /System/Library/Frameworks/WebKit.framework/Versions/A/XPCServices/com.apple.WebKit.WebContent.xpc/Contents/MacOS/com.apple.WebKit.WebContent
  240   0.0  243440 claude
  241   0.1  361200 claude
  242   6.1  475744 /Users/kullanici7/.local/bin/claude
  250   0.0   45584 /Users/kullanici7/.codex/packages/app-server-daemon/releases/0.167.2/bin/codex
  251   1.3  146304 /Users/kullanici7/.opencode/bin/opencode
  260   2.0 2097152 /Applications/Docker.app/Contents/MacOS/com.docker.backend
  261   0.8 1048576 /System/Library/Frameworks/Virtualization.framework/Versions/A/XPCServices/com.apple.Virtualization.VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine
  270   0.1   20480 postgres: selin musteri_db 127.0.0.1(5432) idle
  280   0.0    4096 /Users/kullanici7/Documents/Obsidian/Sifreler/sigorta-takip
"""
DOCKER = "0.10%\t120.5MiB / 7.654GiB\n0.05%\t1.2GiB / 7.654GiB\n"
SECRET_WORDS = ("zim", "Zim", "ZIM", "/Users", "kullanici7", "gizli-proje", "musteri_db", "postgres", "Sifre", "sigorta",
                "Google Chrome Helper", "com.docker.backend", "/Applications", "jdk-21", "runner")


class FakeRun:
    """Answers each macOS command with a canned output; counts the calls."""

    def __init__(self, **over):
        self.out = {"sysctl": SYSCTL, "vm_stat": VM_STAT, "memory_pressure": MEMORY_PRESSURE, "ps": PS, "df": DF,
                    "pmset": PMSET, "docker": DOCKER}
        self.out.update(over)
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append((list(argv), timeout))
        out = self.out.get(os.path.basename(argv[0]))
        if isinstance(out, BaseException):
            raise out
        if out is None:
            raise FileNotFoundError(argv[0])
        return out


def which_all(name):
    return f"/usr/bin/{name}"


class Clock:
    def __init__(self, t=1794000000.0):
        self.t = t

    def __call__(self):
        return self.t


def make(run=None, clock=None, which=which_all, **kw):
    return sistem.Sistem(run=run or FakeRun(), now=clock or Clock(), which=which, own_pid=OWN_PID, **kw)


class ParseTest(unittest.TestCase):
    def test_sysctl_vm_stat_df_pmset(self):
        s = sistem.parse_sysctl(SYSCTL)
        self.assertEqual((s["cekirdek"], s["bellek_bayt"], s["yuk"], s["baski"], s["acilis"]),
                         (10, 17179869184, [4.5, 5.17, 5.07], 1, 1793703075))
        vm = sistem.parse_vm_stat(VM_STAT)
        self.assertEqual(vm["sayfa"], 16384)
        # app memory (anonymous - purgeable) + wired + compressed, like Activity Monitor
        self.assertEqual(vm["kullanilan_bayt"], (314853 - 4033 + 196230 + 360026) * 16384)
        self.assertEqual(sistem.parse_memory_pressure(MEMORY_PRESSURE), 44)
        df = sistem.parse_df(DF)
        # APFS: "Used" of / is only the system volume; fullness is size - available
        self.assertEqual(df["dolu_yuzde"], round(100 * (482797652 - 69822292) / 482797652))
        self.assertAlmostEqual(df["bos_gb"], 69822292 / 1048576, places=1)
        self.assertEqual(sistem.parse_pmset(PMSET), {"yuzde": 94, "durum": "şarj oluyor", "kaynak": "adaptör"})
        self.assertIsNone(sistem.parse_pmset("Now drawing from 'AC Power'\n"))  # a desktop Mac: no battery
        self.assertEqual(sistem.parse_pmset("Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t40%; "
                                            "discharging; 3:10 remaining present: true\n")["durum"], "pilde")
        self.assertEqual(sistem.parse_docker(DOCKER), {"konteyner": 2, "cpu": 0.15, "bellek_mb": round(120.5 + 1.2 * 1024)})
        self.assertEqual(sistem.parse_docker(""), {"konteyner": 0, "cpu": 0.0, "bellek_mb": 0})

    def test_garbage_never_raises(self):
        for f in (sistem.parse_sysctl, sistem.parse_vm_stat, sistem.parse_memory_pressure, sistem.parse_df,
                  sistem.parse_pmset, sistem.parse_docker, sistem.parse_ps):
            with self.subTest(f=f.__name__):
                f("çöp\n\x00 { } : %%%\n")
                f("")

    def test_groups_by_the_executables_base_name_only(self):
        procs = sistem.parse_ps(PS)
        self.assertIn((230, 60.0, 1048576, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                      [(p["pid"], p["cpu"], p["rss_kb"], p["comm"]) for p in procs])
        g = {x["ad"]: x for x in sistem.gruplar(procs, OWN_PID)}
        self.assertEqual(list(g), [n for n in sistem.GRUPLAR if n in g])  # fixed order
        self.assertEqual(g["Java"]["sayi"], 1)  # the ZIM java is not counted anywhere
        self.assertEqual(g["Node"]["sayi"], 2)  # node and an npm process (its title rewritten: "npm exec …")
        self.assertEqual(g["Python"]["sayi"], 1)
        self.assertEqual(g["Ofis sunucusu"], {"ad": "Ofis sunucusu", "sayi": 1, "cpu": 2.0, "bellek_mb": 100})
        self.assertEqual((g["Tarayıcılar"]["sayi"], g["Tarayıcılar"]["cpu"]), (4, 111.5))
        self.assertEqual((g["Claude oturumları"]["sayi"], g["Claude oturumları"]["bosta"]), (3, 2))
        self.assertEqual(g["Codex/OpenCode"]["sayi"], 2)
        self.assertEqual(g["Docker"]["sayi"], 2)  # the backend and its virtual machine
        self.assertEqual(g["Diğer"]["sayi"], 2)  # launchd and postgres
        total = sum(x["sayi"] for x in g.values())
        # the three ZIM processes and the program in the private notes folder are not counted anywhere
        self.assertEqual(total, len(procs) - 4)
        # Colima (Lima) runs Docker's virtual machine too
        colima = [p for p in procs if "com.docker" not in p["comm"]] + [
            {"pid": 900, "cpu": 0.0, "rss_kb": 26976, "comm": "/opt/homebrew/bin/limactl"}]
        g3 = {x["ad"]: x for x in sistem.gruplar(colima, OWN_PID)}
        self.assertEqual(g3["Docker"]["sayi"], 2)  # limactl and the virtual machine
        # the Android emulator's qemu and the Claude desktop app are neither Docker nor a Claude session
        other = [p for p in procs if "com.docker" not in p["comm"]] + [
            {"pid": 901, "cpu": 0.0, "rss_kb": 2097152, "comm": "/x/emulator/qemu/darwin-aarch64/qemu-system-aarch64"},
            {"pid": 902, "cpu": 0.0, "rss_kb": 1024, "comm": "/Applications/Claude.app/Contents/MacOS/Claude"},
            {"pid": 903, "cpu": 0.0, "rss_kb": 1024, "comm": "/Applications/Claude.app/Contents/Frameworks/"
             "Claude Helper (Renderer).app/Contents/MacOS/Claude Helper (Renderer)"}]
        g4 = {x["ad"]: x for x in sistem.gruplar(other, OWN_PID)}
        self.assertNotIn("Docker", g4)
        self.assertEqual(g4["Claude oturumları"]["sayi"], 3)
        # without a Docker process the virtual machine is someone else's
        alone = [p for p in procs if "com.docker" not in p["comm"]]
        g2 = {x["ad"]: x for x in sistem.gruplar(alone, OWN_PID)}
        self.assertNotIn("Docker", g2)


class PrivacyTest(unittest.TestCase):
    """The hard rule: no command line, path, project, container or user name ever reaches the page; ZIM never."""

    def test_nothing_of_a_process_name_or_path_appears_in_the_output(self):
        out = make().durum(sayfa_acik=True)
        text = json.dumps(out, ensure_ascii=False)
        for word in SECRET_WORDS:
            with self.subTest(word=word):
                self.assertNotIn(word.casefold(), text.casefold())
        names = [g["ad"] for g in out["gruplar"]]
        self.assertTrue(set(names) <= set(sistem.GRUPLAR))
        for g in out["gruplar"]:
            self.assertEqual(set(g) - {"bosta"}, {"ad", "sayi", "cpu", "bellek_mb"})  # totals only, no member list

    def test_the_cache_holds_no_process_name_either(self):
        s = make()
        s.durum()
        text = json.dumps(s._son, ensure_ascii=False, default=str)
        for word in ("zim", "/Users", "kullanici7", "musteri_db", "Google Chrome"):
            self.assertNotIn(word.casefold(), text.casefold())

    def test_the_final_filter_drops_any_string_that_reaches_zim_or_the_private_notes(self):
        dirty = {"a": "Java", "b": ["ok", "zim-server", {"c": "/x/Sifreler/y"}], "d": "SİGORTA planı", "n": 3}
        self.assertEqual(sistem.temizle(dirty), {"a": "Java", "b": ["ok", {}], "n": 3})

    def test_only_fixed_commands_with_timeouts_and_no_shell(self):
        run = FakeRun()
        make(run=run).durum()
        progs = [os.path.basename(c[0][0]) for c in run.calls]
        self.assertEqual(sorted(set(progs)), ["df", "docker", "memory_pressure", "pmset", "ps", "sysctl", "vm_stat"])
        for argv, timeout in run.calls:
            self.assertLessEqual(timeout, 3)
        ps = [c[0] for c in run.calls if c[0][0].endswith("ps")][0]
        self.assertEqual(ps[1:], ["-axo", "pid,pcpu,rss,comm"])  # never the command line (args/command)
        docker = [c[0] for c in run.calls if c[0][0].endswith("docker")][0]
        self.assertEqual(docker[1:4], ["stats", "--no-stream", "--format"])
        self.assertNotIn("Name", docker[4])
        self.assertNotIn("ID", docker[4])
        self.assertNotIn("Container", docker[4])

    def test_the_real_runner_has_a_timeout_and_no_shell(self):
        seen = {}

        def fake_run(argv, **kw):
            seen.update(kw, argv=argv)
            return subprocess.CompletedProcess(argv, 0, stdout="x", stderr="")
        real = sistem.subprocess.run
        sistem.subprocess.run = fake_run
        try:
            self.assertEqual(sistem.calistir(["/bin/ps"], 9), "x")
        finally:
            sistem.subprocess.run = real
        self.assertEqual(seen["timeout"], 3)  # capped at 3 s
        self.assertFalse(seen.get("shell", False))
        self.assertEqual(seen["stdin"], subprocess.DEVNULL)


class StatusTest(unittest.TestCase):
    def test_the_status_reads_cpu_memory_disk_battery_uptime(self):
        out = make().durum()
        self.assertEqual(out["cpu"], {"cekirdek": 10, "yuk": [4.5, 5.17, 5.07], "yuk_orani": 0.45})
        self.assertEqual((out["bellek"]["toplam_gb"], out["bellek"]["baski"], out["bellek"]["bos_yuzde"]),
                         (16.0, "normal", 44))
        self.assertEqual(out["disk"]["dolu_yuzde"], 86)
        self.assertEqual(out["pil"]["yuzde"], 94)
        self.assertEqual(out["acik_kalma_sn"], 1794000000 - 1793703075)
        self.assertEqual(out["docker"], {"konteyner": 2, "cpu": 0.15, "bellek_mb": 1349})
        self.assertEqual(out["seviye"], "yesil")

    def test_cached_for_20_seconds(self):
        run, clock = FakeRun(), Clock()
        s = make(run=run, clock=clock)
        s.durum()
        n = len(run.calls)
        clock.t += 19
        s.durum()
        self.assertEqual(len(run.calls), n)
        clock.t += 2
        s.durum()
        self.assertGreater(len(run.calls), n)

    def test_a_failing_or_missing_command_leaves_its_part_empty(self):
        run = FakeRun(pmset=subprocess.TimeoutExpired("pmset", 3), vm_stat=OSError("x"), memory_pressure=None)
        out = make(run=run).durum()
        self.assertIsNone(out["pil"])
        self.assertIsNone(out["bellek"]["kullanilan_gb"])
        self.assertIn("cpu", out)
        # docker only when it is on PATH
        run2 = FakeRun()
        out2 = make(run=run2, which=lambda n: None if n == "docker" else f"/usr/bin/{n}").durum()
        self.assertIsNone(out2["docker"])
        self.assertNotIn("docker", [os.path.basename(c[0][0]) for c in run2.calls])
        # a daemon that does not answer: no docker data
        out3 = make(run=FakeRun(docker=subprocess.CalledProcessError(1, "docker"))).durum()
        self.assertIsNone(out3["docker"])

    def test_the_level_follows_load_and_memory_pressure(self):
        def level(load, pressure=1):
            text = SYSCTL.replace("{ 4.50", "{ %.2f" % load).replace("level: 1", f"level: {pressure}")
            return make(run=FakeRun(sysctl=text)).durum()["seviye"]
        self.assertEqual(level(4.5), "yesil")
        self.assertEqual(level(8.0), "sari")
        self.assertEqual(level(12.0), "kirmizi")
        self.assertEqual(level(1.0, 2), "sari")
        self.assertEqual(level(1.0, 4), "kirmizi")

    def test_the_summary_for_the_scene_never_runs_a_command(self):
        run = FakeRun()
        s = make(run=run)
        self.assertIsNone(s.ozet())
        self.assertEqual(run.calls, [])
        s.durum()
        n = len(run.calls)
        self.assertEqual(s.ozet(), {"seviye": "yesil", "oneri": 1, "domain_sorunu": 0})  # idle Docker
        self.assertEqual(len(run.calls), n)


    def test_the_summary_never_waits_for_a_sample_being_taken(self):
        gate, inside = threading.Event(), threading.Event()
        run, clock = FakeRun(), Clock()
        s = make(run=run, clock=clock)
        s.durum()
        clock.t += 21
        orig_call = run.__call__

        def slow(argv, timeout):
            if argv[0].endswith("ps"):
                inside.set()
                gate.wait(5)
            return orig_call(argv, timeout)
        s.run_cmd = slow
        t = threading.Thread(target=s.durum)
        t.start()
        self.assertTrue(inside.wait(5))
        t0 = time.monotonic()
        self.assertEqual(s.ozet()["seviye"], "yesil")  # the cached sample …
        self.assertLess(time.monotonic() - t0, 0.5)  # … at once, while the gate is still closed
        self.assertFalse(gate.is_set())
        gate.set()
        t.join(5)
        self.assertFalse(t.is_alive())


class SuggestionTest(unittest.TestCase):
    def kinds(self, out):
        return [o["tur"] for o in out["oneriler"]]

    def test_no_suggestion_on_a_calm_computer(self):
        # Docker works (its containers use CPU), the browser is busy but the office page is closed
        calm = FakeRun(docker="25.0%\t1GiB / 7GiB\n")
        self.assertEqual(make(run=calm).durum(sayfa_acik=False)["oneriler"], [])

    def test_idle_docker_disk_memory_and_idle_claude_sessions(self):
        ps = PS + "".join(f"  {300 + i}   0.0  200000 claude\n" for i in range(5))
        df = DF.replace("69822292", "24139882")  # 95 % full
        sysctl = SYSCTL.replace("level: 1", "level: 2")
        out = make(run=FakeRun(ps=ps, df=df, sysctl=sysctl, docker="0.01%\t10MiB / 7GiB\n")).durum()
        kinds = self.kinds(out)
        for k in ("docker-bosta", "claude-bosta", "disk", "bellek"):
            self.assertIn(k, kinds)
        text = json.dumps(out["oneriler"], ensure_ascii=False)
        for word in ("kapatıldı", "silindi", "kill"):
            self.assertNotIn(word, text)  # the office never closes or deletes anything itself
        self.assertIn("Selin", text)  # the tests' owner name (test/sahip_yasaklari.py)

    def test_busy_docker_is_not_idle(self):
        out = make(run=FakeRun(docker="85.0%\t1GiB / 7GiB\n")).durum()
        self.assertNotIn("docker-bosta", self.kinds(out))

    def test_sustained_high_cpu_needs_three_samples_over_150(self):
        hot = PS.replace("  200  80.0", "  200 180.0")
        run, clock = FakeRun(ps=hot), Clock()
        s = make(run=run, clock=clock)
        seen = []
        for _ in range(3):
            seen.append("cpu-yuksek" in self.kinds(s.durum()))
            clock.t += 21
        self.assertEqual(seen, [False, False, True])
        run.out["ps"] = PS
        self.assertNotIn("cpu-yuksek", self.kinds(s.durum()))
        text = [o["metin"] for o in make(run=FakeRun(ps=hot)).durum()["oneriler"]]
        self.assertFalse(any("zim" in t.casefold() for t in text))

    def test_a_browser_over_one_core_suggests_hafif_only_while_the_page_is_open(self):
        hot = PS.replace("  230  60.0", "  230 120.0")
        self.assertIn("?hafif=1", json.dumps(make(run=FakeRun(ps=hot)).durum(sayfa_acik=True)["oneriler"]))
        self.assertNotIn("tarayici", self.kinds(make(run=FakeRun(ps=hot)).durum(sayfa_acik=False)))


class FakeCeo:
    def __init__(self):
        self.sent = []

    def enqueue(self, text, key):
        if any(k == key for _, k in self.sent):
            return "duplicate"
        self.sent.append((text, key))
        return "queued"


class FakeNet:
    """https(domain) -> {acildi, durum_kodu, gun, hata}; dns(domain) -> [ip]; mx(domain) -> [host] or None."""

    def __init__(self):
        self.https_out = {}
        self.dns_out = {}
        self.mx_out = {}
        self.calls = []

    def https(self, domain):
        self.calls.append(("https", domain))
        r = self.https_out.get(domain, {"acildi": True, "durum_kodu": 200, "gun": 80, "hata": None})
        if isinstance(r, BaseException):
            raise r
        return r

    def dns(self, domain):
        self.calls.append(("dns", domain))
        return self.dns_out.get(domain, ["203.0.113.10"])

    def mx(self, domain):
        self.calls.append(("mx", domain))
        return self.mx_out.get(domain, ["mx1.example.net"])


class DomainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.durum = self.tmp.name
        self.cfg = {"projects": {"blog": {"path": "/x", "sistem": {"domainler": ["blog.example", "https://www.blog.example/"],
                                                                       "eposta_domaini": "blog.example",
                                                                       "cloudflare": True}},
                                 "diger": {"path": "/y"}}}
        self.net = FakeNet()
        self.ceo = FakeCeo()
        self.clock = Clock()

    def tearDown(self):
        self.tmp.cleanup()

    def kontrol(self, cfg=None):
        return sistem.DomainKontrol(lambda: cfg or self.cfg, self.durum, self.ceo, https=self.net.https,
                                    dns=self.net.dns, mx=self.net.mx, now=self.clock)

    def test_no_list_yet(self):
        k = self.kontrol({"projects": {"blog": {"path": "/x"}}})
        self.assertFalse(k.kontrol_et())
        self.assertEqual(self.net.calls, [])  # nobody is contacted
        out = sistem.domain_ozeti(self.durum, {"projects": {"blog": {"path": "/x"}}})
        self.assertFalse(out["liste_var"])
        self.assertEqual(out["metin"], "Domain listesi henüz yok — Ar-Ge ilk çalışmasında soracak")

    def test_only_the_registered_domains_are_contacted_and_cached(self):
        self.net.dns_out["blog.example"] = ["104.16.1.1", "104.16.2.2"]
        k = self.kontrol()
        self.assertTrue(k.kontrol_et())
        domains = {d for _, d in self.net.calls}
        self.assertEqual(domains, {"blog.example", "www.blog.example"})
        with open(os.path.join(self.durum, "sistem", "domainler.json"), encoding="utf-8") as f:
            cache = json.load(f)
        self.assertIn("blog.example", cache["domainler"])
        out = sistem.domain_ozeti(self.durum, self.cfg)
        self.assertTrue(out["liste_var"])
        row = [d for d in out["domainler"] if d["domain"] == "blog.example"][0]
        self.assertEqual((row["https"]["durum_kodu"], row["https"]["gun"], row["dns"]["cloudflare"]), (200, 80, True))
        www = [d for d in out["domainler"] if d["domain"] == "www.blog.example"][0]
        self.assertFalse(www["dns"]["cloudflare"])  # 203.0.113.10 is not in Cloudflare's ranges
        self.assertEqual(out["eposta"], [{"proje": "blog", "domain": "blog.example", "mx": ["mx1.example.net"]}])
        self.assertEqual(self.ceo.sent, [])  # nothing wrong

    def test_mx_unknown_without_dig(self):
        self.net.mx_out["blog.example"] = None
        self.kontrol().kontrol_et()
        self.assertEqual(sistem.domain_ozeti(self.durum, self.cfg)["eposta"][0]["mx"], "bilinmiyor")

    def test_invalid_and_zim_domains_are_never_contacted(self):
        cfg = {"projects": {"p": {"sistem": {"domainler": ["zim.example.com", "kötü domain", "a;rm -rf", "-x.com",
                                                          "ok.example"], "eposta_domaini": "zim-mail.example"}}}}
        self.kontrol(cfg).kontrol_et()
        self.assertEqual({d for _, d in self.net.calls}, {"ok.example"})
        self.assertNotIn("zim", json.dumps(sistem.domain_ozeti(self.durum, cfg)).casefold())

    def test_one_notice_per_problem_until_it_changes(self):
        k = self.kontrol()
        self.net.https_out["blog.example"] = {"acildi": False, "durum_kodu": None, "gun": None, "hata": "zaman aşımı"}
        k.kontrol_et()
        k.kontrol_et()
        down = [t for t, _ in self.ceo.sent if "açılmıyor" in t]
        self.assertEqual(len(down), 1)
        self.assertTrue(down[0].startswith("[Ofis · sistem]\n"))
        self.assertIn("blog.example", down[0])
        # it opens again, then fails again: a new problem, a new notice
        self.net.https_out["blog.example"] = {"acildi": True, "durum_kodu": 200, "gun": 80, "hata": None}
        k.kontrol_et()
        self.clock.t += 3600
        self.net.https_out["blog.example"] = {"acildi": False, "durum_kodu": 503, "gun": 80, "hata": None}
        k.kontrol_et()
        self.assertEqual(len([t for t, _ in self.ceo.sent if "açılmıyor" in t]), 2)
        self.assertEqual(sistem.domain_ozeti(self.durum, self.cfg)["sorun_sayisi"], 1)

    def test_certificate_under_14_days_once(self):
        k = self.kontrol()
        self.net.https_out["www.blog.example"] = {"acildi": True, "durum_kodu": 301, "gun": 13, "hata": None,
                                                     "bitis": "Nov 25 12:00:00 2026 GMT"}
        k.kontrol_et()
        self.net.https_out["www.blog.example"]["gun"] = 12
        k.kontrol_et()
        cert = [t for t, _ in self.ceo.sent if "sertifika" in t]
        self.assertEqual(len(cert), 1)
        self.assertIn("13 gün", cert[0])
        self.net.https_out["www.blog.example"] = {"acildi": True, "durum_kodu": 200, "gun": 14, "hata": None}
        k.kontrol_et()
        self.assertEqual(len([t for t, _ in self.ceo.sent if "sertifika" in t]), 1)

    def test_a_dns_change_is_told_once(self):
        k = self.kontrol()
        k.kontrol_et()  # the first check only records
        self.assertEqual(self.ceo.sent, [])
        self.net.dns_out["www.blog.example"] = ["198.51.100.7"]
        k.kontrol_et()
        k.kontrol_et()
        dns = [t for t, _ in self.ceo.sent if "DNS" in t]
        self.assertEqual(len(dns), 1)
        self.assertIn("198.51.100.7", dns[0])
        # a lookup that failed is no change
        self.net.dns_out["www.blog.example"] = []
        k.kontrol_et()
        self.assertEqual(len([t for t, _ in self.ceo.sent if "DNS" in t]), 1)

    def test_cloudflare_moving_between_its_own_addresses_is_no_change(self):
        self.net.dns_out["blog.example"] = ["104.16.1.1"]
        k = self.kontrol()
        k.kontrol_et()
        self.net.dns_out["blog.example"] = ["172.67.3.3"]
        k.kontrol_et()
        self.assertEqual(self.ceo.sent, [])

    def test_the_scene_summary_counts_open_problems_and_an_emptied_list_clears_them(self):
        self.net.https_out["blog.example"] = {"acildi": False, "durum_kodu": None, "gun": 5, "hata": "zaman aşımı"}
        self.kontrol().kontrol_et()
        self.assertEqual(sistem.domain_sorunu(self.durum), 2)  # not opening + the certificate
        s = make(durum_dir=self.durum, cfg=lambda: self.cfg)
        s.durum()
        self.assertEqual(s.ozet()["domain_sorunu"], 2)
        self.assertEqual(s.durum()["domainler"]["sorun_sayisi"], 2)
        self.kontrol({"projects": {"blog": {"path": "/x"}}}).kontrol_et()
        self.assertEqual(sistem.domain_sorunu(self.durum), 0)

    def test_a_rotating_address_pool_is_no_change(self):
        self.net.dns_out["blog.example"] = ["198.51.100.1", "198.51.100.2"]
        k = self.kontrol()
        k.kontrol_et()
        self.net.dns_out["blog.example"] = ["198.51.100.2", "198.51.100.3"]  # one address stays
        k.kontrol_et()
        self.assertEqual(self.ceo.sent, [])

    def test_a_notice_that_could_not_be_queued_is_tried_again(self):
        class Flaky(FakeCeo):
            fail = True

            def enqueue(self, text, key):
                if Flaky.fail:
                    raise OSError("queue file")
                return super().enqueue(text, key)
        self.ceo = Flaky()
        self.net.https_out["blog.example"] = {"acildi": False, "durum_kodu": None, "gun": None, "hata": "zaman aşımı"}
        k = self.kontrol()
        k.kontrol_et()
        self.assertEqual(self.ceo.sent, [])
        Flaky.fail = False
        k.kontrol_et()
        k.kontrol_et()
        self.assertEqual(len([t for t, _ in self.ceo.sent if "açılmıyor" in t]), 1)

    def test_a_stalled_name_lookup_times_out(self):
        real = sistem.socket.getaddrinfo
        sistem.socket.getaddrinfo = lambda *a, **k: time.sleep(2) or []
        try:
            t0 = time.monotonic()
            self.assertEqual(sistem.dns_kontrol("site.example", timeout=0.2), [])
            self.assertLess(time.monotonic() - t0, 1.5)
        finally:
            sistem.socket.getaddrinfo = real

    def test_a_network_error_is_a_site_that_does_not_open(self):
        self.net.https_out["blog.example"] = OSError("ağ yok")
        self.kontrol().kontrol_et()
        self.assertEqual(len([t for t, _ in self.ceo.sent if "açılmıyor" in t]), 1)

    def test_cloudflare_ranges(self):
        for ip, want in (("104.16.0.1", True), ("172.71.255.255", True), ("173.245.48.5", True), ("8.8.8.8", False),
                         ("not-an-ip", False)):
            with self.subTest(ip=ip):
                self.assertEqual(sistem.cloudflare_mi(ip), want)

    def test_the_loop_checks_a_few_times_a_day(self):
        k = self.kontrol()
        self.assertTrue(k.vakti_geldi())
        k.kontrol_et()
        self.assertFalse(k.vakti_geldi())
        self.clock.t += sistem.DOMAIN_ARALIK_SN + 1
        self.assertTrue(k.vakti_geldi())
        stop = threading.Event()
        stop.set()
        k.run(stop, interval=0.01)  # returns at once when stopped

    def test_the_real_network_functions_have_timeouts(self):
        import inspect
        src = inspect.getsource(sistem.https_kontrol)
        self.assertIn("timeout", src)
        self.assertIn("create_default_context", src)
        self.assertIn('"HEAD"', src)
        self.assertIn("timeout", inspect.getsource(sistem.mx_kontrol))


if __name__ == "__main__":
    unittest.main()
