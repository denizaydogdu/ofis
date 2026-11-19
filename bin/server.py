#!/usr/bin/env python3
"""Ofis — local office page: watch the office sessions in 3D and chat with the CEO session; runs the post office
(bin/postoffice.py) that carries project reports to the CEO and the owner's answers back to the projects, stops jobs over
their budget or call limit, runs the jobs' Kontrol (bin/kontrol.py) and writes the scorecard (bin/karne.py).

    python3 bin/server.py            # http://127.0.0.1:8800 (or the next free port up to 8819)

At login it can be started by launchd (bin/autostart.py install). A second server exits 0 ("already running") so
launchd does not restart it; at start it prints a marker line and, when the vault cannot be read (macOS privacy may
refuse ~/Documents to a launchd-started python), one Turkish error line that `autostart.py status` shows.

Python standard library only. Binds 127.0.0.1. Every request must carry Host 127.0.0.1:<port> or localhost:<port>
(DNS-rebinding guard). POST additionally needs the exact Origin, Content-Type application/json, a body of at most
16 KB (POST /api/yakala: the file limit of ofis.json yakala in base64, bin/yakala.py govde_siniri) and the X-Ofis-Token header whose value is generated at startup and injected into the served index.html.
No CORS headers are ever sent. The page's endpoints refuse an Authorization header. POST /api/npc-sohbet (bin/npc_sohbet.py:
a staff character answers a short question from the office's own state with one tool-less `claude -p` call) is 409
unless ofis.json npc_sohbet.acik is true. The Jarvis gate (bin/jarvis.py:
GET /.well-known/agent-card.json, POST /a2a with its own bearer key, loopback only, no Origin) is 404 unless ofis.json
jarvis.acik is true.
"""
import base64
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adimlar  # noqa: E402
import akis  # noqa: E402
import ayarlar  # noqa: E402
import autostart  # noqa: E402
import ceo as ceo_mod  # noqa: E402
import claude_cli  # noqa: E402
import danisman  # noqa: E402
import jarvis  # noqa: E402
import denetci  # noqa: E402
import devir  # noqa: E402
import dil  # noqa: E402
import duyuru  # noqa: E402
import jobs  # noqa: E402
import karne  # noqa: E402
import launch  # noqa: E402
import yasaklar  # noqa: E402
import model_durum  # noqa: E402
import model_secimi  # noqa: E402
import mudur  # noqa: E402
import kullanim  # noqa: E402
import muhasebe  # noqa: E402
import olaylar  # noqa: E402
import ozet  # noqa: E402
import arge  # noqa: E402
import gunsonu  # noqa: E402
import talimat_denetimi  # noqa: E402
import notyolu  # noqa: E402
import npc_sohbet  # noqa: E402
import postoffice as postoffice_mod  # noqa: E402
import rapor  # noqa: E402
import sahip  # noqa: E402
import sistem  # noqa: E402
import sorumlu  # noqa: E402
import state as state_mod  # noqa: E402
import task_detail  # noqa: E402
import transcript  # noqa: E402
import yakala  # noqa: E402
import zamanla  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")
DURUM_DIR = os.path.join(ROOT, "durum")
PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
PORTS = range(8800, 8820)
MAX_BODY = 16 * 1024
MAX_TEXT = 4000
MAX_CHAT_LINES = 300
POLL_SECONDS = 1.5
HEARTBEAT_SECONDS = 15.0
IDLE_AFTER_SECONDS = 30.0
ANSWERED_CODE = "cevap-iletildi"  # the page shows the card as answered instead of an error
ALREADY_SENT_TEXT = "Bu karara cevabın zaten iletildi; CEO notu güncelleyecek."
ANSWERED_TEXT = "Bu karar zaten cevaplanmış."
INJECT_MARKER = "%%OFIS_PAGE_NONCE%%"  # replaced in index.html with the per-start request header value
IMPORTMAP = re.compile(r'<script type="importmap">(.*?)</script>', re.S)
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
         ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}


class Hub:
    """Builds state/chat snapshots, polls while someone is watching, and wakes SSE streams on change."""

    def __init__(self, office, root):
        self.office = office
        self.root = root
        self.events = None  # olaylar.Olaylar of the running server (main), None in tests
        self.cond = threading.Condition()
        self._refresh_lock = threading.Lock()
        self.state = None
        self.state_json = None
        self.state_version = 0
        self.chat = []
        self.chat_key = None
        self.chat_version = 0
        self.answered = None  # an AnswerLog (set by App): decisions whose answer went to the CEO
        self.subscribers = 0
        self.last_access = 0.0
        self.refreshed_at = 0.0

    def _chat(self, sid):
        """(key, lines): the CEO's chat — the sessions it was rotated away from (bin/ceo.py rotation, at most three,
        oldest first) and then the current one, so the page's history stays continuous across a rotation; handoff
        blocks checked against the ids the server recorded (transcript.verify_handoffs)."""
        if not sid:
            return None, []
        ceo = self.office.ceo
        earlier = [i for i in ceo.earlier_ids() if i != sid] if hasattr(ceo, "earlier_ids") else []
        key, lines = [], []
        for i in earlier + [sid]:
            st = self.office.transcripts.get(self.root, i, with_chat=True)
            if st is None:
                if i == sid:
                    return None, []
                continue
            key.append((i, st.chat_total))
            lines.extend(st.chat)
        ids = ceo.handoff_ids() if hasattr(ceo, "handoff_ids") else []
        lines = transcript.verify_handoffs(lines, ids)
        return tuple(key + [tuple(ids)]), lines[-MAX_CHAT_LINES:]

    def full_chat(self, sid):
        """The current CEO session's whole chat (polled to the end of its transcript), for the handoff note."""
        with self._refresh_lock:
            st = self.office.transcripts.get(self.root, sid, with_chat=True) if sid else None
            if st is None:
                return []
            for _ in range(200):  # MAX_READ bytes per poll
                try:
                    if st.offset >= os.stat(st.path).st_size:
                        break
                except OSError:
                    break
                st.poll()
            return transcript.verify_handoffs(list(st.chat), self.office.ceo.handoff_ids())

    def refresh(self):
        with self._refresh_lock:
            state = self.office.build()
            sent = self.answered.notes() if self.answered else set()
            for d in state["decisions"] + state.get("mudur_kararlari", []):
                d["answer_sent"] = d["note"] in sent
            encoded = json.dumps(state, ensure_ascii=False, sort_keys=True)
            key, chat = self._chat(state["ceo"].get("session_id"))
            with self.cond:
                changed = False
                if encoded != self.state_json:
                    self.state, self.state_json = state, encoded
                    self.state_version += 1
                    changed = True
                if key != self.chat_key:
                    self.chat_key, self.chat = key, list(chat)
                    self.chat_version += 1
                    changed = True
                self.refreshed_at = time.monotonic()
                if changed:
                    self.cond.notify_all()

    def touch(self):
        self.last_access = time.monotonic()

    def usage_detail(self, project):
        # transcript readers are shared with refresh(); read them under the same lock
        with self._refresh_lock:
            return self.office.usage_detail(project)

    def _path_of(self, sid):
        if not transcript.valid_session_id(sid):
            return None
        path = transcript.transcript_path(self.office.projects_dir, self.root, sid)
        return None if transcript.forbidden_folder(os.path.dirname(path)) else path

    def _ceo_path(self, ceo):
        return self._path_of(ceo.get("session_id"))

    def _earlier_paths(self, ceo):
        """The transcripts of the sessions the CEO was rotated away from (oldest first), for the steps and turns."""
        sid = ceo.get("session_id")
        ctl = self.office.ceo
        ids = ctl.earlier_ids() if hasattr(ctl, "earlier_ids") else []
        return [p for p in (self._path_of(i) for i in ids if i != sid) if p]

    def ceo_steps(self):
        """GET /api/ceo/adimlar: the CEO's recent tool steps (bin/adimlar.py) with its state from the snapshot."""
        state, _ = self.snapshot()
        ceo = (state or {}).get("ceo") or {}
        return adimlar.ceo_adimlari(self._ceo_path(ceo), ceo.get("state"), onceki=self._earlier_paths(ceo))

    def ceo_turns(self):
        """GET /api/ceo/turlar: per CEO turn (newest first) its steps, the jobs it opened (title and role from the
        office state), cost and tokens — the footer under each reply; kapaniyor while the reply is written but the turn
        has not ended (bin/adimlar.py). Turns of the sessions the CEO was rotated away from come after the current
        session's."""
        state, _ = self.snapshot()
        state = state or {}
        ceo = state.get("ceo") or {}
        out = adimlar.ceo_turlari(self._ceo_path(ceo), onceki=self._earlier_paths(ceo))
        adimlar.isleri_tamamla(out["turlar"], list(state.get("tasks") or []) + list(state.get("board") or []),
                               self.office.cfg)
        return out

    def snapshot(self):
        self.touch()
        if self.state is None or time.monotonic() - self.refreshed_at > POLL_SECONDS * 2:
            self.refresh()
        with self.cond:
            return self.state, self.chat

    def run(self, stop_event):
        while not stop_event.wait(POLL_SECONDS):
            if self.subscribers or time.monotonic() - self.last_access < IDLE_AFTER_SECONDS:
                try:
                    self.refresh()
                except Exception as e:  # keep polling; the page shows stale data rather than crashing
                    print(f"ofis: refresh failed: {type(e).__name__}: {e}", file=sys.stderr)
                    if self.events is not None:
                        self.events.record("hata", f"sayfa yenilenemedi: {type(e).__name__}: {e}")


class AnswerLog:
    """Decision notes whose answer the owner already sent to the CEO, kept across restarts (bug seen live: after a restart
    the page offered the answer box again while the first answer was still queued, and the CEO got it twice).

    A note counts as answered when its answer is waiting in the CEO queue (durum/ceo-queue.jsonl: queued or being
    delivered — the drainer removes an item only after claude accepted it) or is listed in durum/ceo-cevaplar.txt
    (written right after a delivery or a queueing succeeded). A delivery that failed is not listed: the owner may send it
    again. `lock` serialises check + delivery + record, so two quick clicks cannot both pass."""

    MAX_LINES = 1000
    RESEND_AFTER = 30 * 60  # seconds: a delivered answer the CEO never recorded (its turn died) may be sent again

    def __init__(self, durum_dir, ceo, clock=time.time):
        self.path = os.path.join(durum_dir, "ceo-cevaplar.txt")
        self.ceo = ceo
        self.clock = clock
        self.lock = threading.Lock()

    def _entries(self):
        """[(note, epoch seconds)] — lines are "<note>\\t<epoch>"."""
        try:
            with open(self.path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except (OSError, UnicodeDecodeError):
            return []
        out = []
        for line in lines:
            note, _, stamp = line.partition("\t")
            try:
                out.append((note, float(stamp)))
            except ValueError:
                continue
        return out

    def notes(self):
        """Notes whose answer is queued for the CEO, or was sent to it less than RESEND_AFTER ago (after that the
        note is still pending only when the CEO never recorded the answer: the owner may send it again)."""
        now = self.clock()
        out = set(n for n, at in self._entries() if n and now - at < self.RESEND_AFTER)
        for item in self.ceo.queue():
            text = item.get("text", "")
            prefix = sahip.answer_prefix_of(text)  # also the old "[Deniz · karar cevabı]" queued before an update
            if prefix:
                out.add(text[len(prefix):].split("\n", 1)[0].strip())
        return out

    def add(self, note):
        lines = [f"{n}\t{at:.0f}" for n, at in self._entries() if n and n != note][-(self.MAX_LINES - 1):] + \
            [f"{note}\t{self.clock():.0f}"]
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("".join(line + "\n" for line in lines))
        os.replace(tmp, self.path)


PAGE_KEY_FILE = "sayfa_anahtari"
_PAGE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def anahtar_dosyasi(durum_dir, name):
    """(key, persisted) of a key file durum/<name>: read when it holds a valid key, else a new one written atomically
    with mode 0600 (persisted False when the folder is unwritable: the key then lives for this run only). Never
    logged. Used for the page token and the Jarvis key (bin/jarvis.py)."""
    path = os.path.join(durum_dir, name)
    try:
        with open(path, encoding="ascii") as f:
            value = f.read().strip()
        if _PAGE_KEY_RE.match(value):
            return value, True
    except (OSError, ValueError):
        pass
    value = secrets.token_urlsafe(32)
    try:
        os.makedirs(durum_dir, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(value + "\n")
        os.replace(tmp, path)
    except OSError:
        return value, False
    return value, True


def sayfa_anahtari_yukle(durum_dir):
    """The page token, stable across server restarts (an open page keeps working). Kept in durum/sayfa_anahtari
    (mode 0600, created atomically); regenerated only when the file is missing or not a valid token. Never logged."""
    return anahtar_dosyasi(durum_dir, PAGE_KEY_FILE)[0]


class App:
    def __init__(self, cfg, root=ROOT, web_dir=WEB_DIR, durum_dir=DURUM_DIR, projects_dir=PROJECTS_DIR,
                 claude_bin=None, page_nonce=None, ceo_kwargs=None, config_path=None, log=None):
        self.cfg = cfg
        self.root = root
        self.web_dir = os.path.realpath(web_dir)
        self.page_nonce = page_nonce or sayfa_anahtari_yukle(durum_dir)
        self.port = None
        self.cli = claude_cli.ClaudeCLI(claude_bin=claude_bin)
        self.ceo = ceo_mod.CeoController(self.cli, root, cfg["ceo_session"], durum_dir, projects_dir,
                                         **(ceo_kwargs or {}))
        self.office = state_mod.OfficeState(cfg, self.cli, self.ceo, root, projects_dir, durum_dir)
        # Post office: project reports (durum/gelen) and answers to projects (durum/giden). Always on, page or not.
        self.postoffice = postoffice_mod.PostOffice(cfg, self.cli, self.ceo, durum_dir, projects_dir,
                                                    channel_kwargs=ceo_kwargs, config_path=config_path, log=log)
        self.office.postoffice = self.postoffice
        # Step 4: the dispatcher starts a job whose model is on a concrete quota with its backup model
        self.postoffice.dispatcher.kota = self.office.claude_kotalari
        self.office.sunucu = {"baslangic": time.strftime("%Y-%m-%dT%H:%M:%S"), "pid": os.getpid()}
        self.config_path = config_path
        # the Sunucu odası (bin/sistem.py): the computer's status, sampled only while the page is watched (main())
        self.sistem = sistem.Sistem(durum_dir=durum_dir, cfg=self.current_config)
        # the usage popup under the limit pill (GET /api/kullanim): who used the plan in the 5-hour / weekly window
        self.kullanim = kullanim.Kullanim(projects_dir, root, durum_dir, os.path.expanduser(cfg["vault_ofis"]))
        # NPC chat (bin/npc_sohbet.py, ofis.json npc_sohbet): one tool-less model call per question, from the page's
        # own state snapshot; one at a time, an hourly limit
        self.npc_sohbet = npc_sohbet.Sohbet(durum_dir, self.cli, self.current_config,
                                            lambda: self.hub.snapshot()[0])
        self.office.sistem = self.sistem
        self.vault_problem = None  # main(): the Obsidian access problem of this start (the İdari işler card)
        self.hub = Hub(self.office, root)
        self.answers = AnswerLog(durum_dir, self.ceo)
        self.hub.answered = self.answers
        # the Jarvis gate (bin/jarvis.py, ofis.json jarvis): status and decisions over A2A; its key is made on first use
        self.jarvis = jarvis.Kapi(self, anahtar_dosyasi, log=lambda line: print(line, file=sys.stderr, flush=True))
        # CEO session rotation (bin/ceo.py, ofis.json ceo_yenileme): settings as they are now and the handoff note
        self.ceo.ayarlar = self.current_config
        self.ceo.devir_notu = self.devir_notu
        self.vault_ofis = os.path.expanduser(cfg["vault_ofis"])
        self.stop_event = threading.Event()
        self._refreshers = []  # refresh threads started by deliver(); join_refreshes() waits for them (tests)
        # Scratch folder for the CEO's input files (`ofis.py ekle --brief-dosya`, `cevapla --dosya`).
        os.makedirs(os.path.join(durum_dir, "taslak"), exist_ok=True)

    def current_config(self):
        """ofis.json as it is now (the CEO may have added a project's domain list since the start), else the start's."""
        if self.config_path:
            try:
                cfg = launch.load(self.config_path)
                self._config_warned = False
                return cfg
            except Exception as e:  # unreadable or not an object: the start's config, said once until it reads again
                if not getattr(self, "_config_warned", False):
                    self._config_warned = True
                    print(f"ofis: ofis.json okunamadı ({type(e).__name__}); başlangıçtaki ayarlar kullanılıyor",
                          file=sys.stderr, flush=True)
        return self.cfg

    def ayarlari_yenile(self, zorla=False):
        """Takes ofis.json's projects, free reviewers' list and office name into the one cfg every thread shares
        (bin/ayarlar.py Yenileyici, the post office's: one lock, one mtime). zorla: read even when the mtime looks
        unchanged (right after this server wrote the file)."""
        return self.postoffice.ayarlar.yenile(zorla=zorla)

    def ayar_degistir(self, govde):
        """One POST /api/ayarlar body -> (HTTP status, JSON body). The file is written under the job lock
        (bin/ayarlar.py islem), the running cfg refreshed at once, the page refreshed, and a project change told to
        the CEO once."""
        if not self.config_path:
            m = dil.t("Ayar dosyası bilinmiyor; ayarlar bu sunucudan değiştirilemez.", self.cfg)
            return 409, {"error": m, "hatalar": [m], "alanlar": [""]}
        try:
            sonuc = ayarlar.islem(self.config_path, self.office.durum_dir, govde)
        except ayarlar.Hata as e:
            # each error in the display language with its form field ("" = the form as a whole; web/ayarlar.js)
            hatalar = [dil.cevir(x, self.cfg) for x in e.hatalar]
            return e.durum, {"error": hatalar[0] if hatalar else dil.t("geçersiz istek", self.cfg),
                             "hatalar": hatalar, "alanlar": [getattr(x, "alan", "") for x in e.hatalar]}
        except (OSError, ValueError, jobs.JobError) as e:
            m = dil.t("ayarlar yazılamadı: {tur}", self.cfg, tur=type(e).__name__)
            return 500, {"error": m, "hatalar": [m], "alanlar": [""]}
        if sonuc.pop("dil_degisti", False):
            # the CEO's system text and reminder line follow the language: a fresh CEO session at the next delivery
            # (the same flag as `ofis.py ceo-yenile`)
            try:
                ceo_mod.yenile_iste(self.office.durum_dir, datetime.now().isoformat(timespec="seconds"))
            except OSError as e:
                print(f"ofis: CEO yenileme isteği yazılamadı: {type(e).__name__}", file=sys.stderr)
        self.ayarlari_yenile(zorla=True)
        out = {"tamam": True, **sonuc, "guven": None, "ipucu": ""}
        entry = (self.cfg.get("projects") or {}).get(sonuc["ad"]) if sonuc["ad"] else None
        if sonuc["islem"] in ("proje-ekle", "proje-guncelle") and isinstance(entry, dict):
            out["guven"], out["ipucu"] = ayarlar.guven(entry.get("path") or "")
        text = ayarlar.bildirim(sonuc, self.cfg)
        if text:
            try:
                self.ceo.enqueue(text, f"ayarlar-{sonuc['islem']}-{sonuc['ad']}-{time.time_ns()}")
            except (OSError, ValueError) as e:  # the change is written; only the notice is missing
                print(f"ofis: ayar bildirimi kuyruğa alınamadı: {type(e).__name__}", file=sys.stderr)
        t = threading.Thread(target=self._refresh_quietly, daemon=True)
        self._refreshers = [x for x in self._refreshers if x.is_alive()] + [t]
        t.start()
        out["ayarlar"] = ayarlar.ozet(self.cfg, self.office.durum_dir)
        return 200, out

    def devir_notu(self, neden, kuyruk, kimlik):
        """The handoff block for a rotated CEO session (bin/devir.py): the office's own data, no model call. Runs under
        the CEO's delivery lock (bin/ceo.py _rotate)."""
        cfg = self.current_config()
        office = self.office
        now = datetime.now()

        def safe(fn, default):
            try:
                return fn()
            except Exception as e:  # noqa: BLE001 — one missing section never blocks the rotation
                print(f"ofis: devir notu bölümü okunamadı: {type(e).__name__}", file=sys.stderr)
                return default
        return devir.metin({
            "kimlik": kimlik, "neden": neden, "simdi": now, "kuyruk": kuyruk,
            "isler": safe(lambda: state_mod.recent_tasks(office.vault_ofis, limit=0, cfg=cfg,
                                                         durum_dir=office.durum_dir), []),
            "kararlar": safe(lambda: state_mod.pending_decisions(office.vault_ofis), []),
            "mudur": safe(lambda: mudur.kararlar(office.vault_ofis), []),
            "sohbet": safe(lambda: self.hub.full_chat(self.ceo.session_id()), []),
            "zamanlanmis": safe(lambda: zamanla.summaries(office.durum_dir, now), []),
            "danisman": safe(lambda: danisman.page(cfg, office.durum_dir), None)})

    def page_open(self):
        """True while an office page is connected (the SSE stream)."""
        return self.hub.subscribers > 0

    def page_watched(self):
        return self.hub.subscribers > 0 or time.monotonic() - self.hub.last_access < IDLE_AFTER_SECONDS

    def start_threads(self):
        # The Kontrol worker and the Codex reviewer (phase 4) have their own threads: a job's Kontrol or a review
        # may run for minutes and must never hold up the post office tick (reports, answers, CEO notices).
        for target in (self.hub.run, self.ceo.run_drainer, self.postoffice.run, self.postoffice.kontrol.run,
                       self.postoffice.codex.run, self.postoffice.mudur.run):
            threading.Thread(target=target, args=(self.stop_event,), daemon=True).start()

    def allowed_hosts(self):
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def allowed_origins(self):
        return {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}

    def index_html(self):
        with open(os.path.join(self.web_dir, "index.html"), encoding="utf-8") as f:
            html = f.read()
        return html.replace(INJECT_MARKER, self.page_nonce)

    @staticmethod
    def csp(html):
        hashes = " ".join(
            "'sha256-" + base64.b64encode(hashlib.sha256(m.group(1).encode()).digest()).decode() + "'"
            for m in IMPORTMAP.finditer(html))
        return ("default-src 'self'; script-src 'self' " + hashes + "; style-src 'self'; img-src 'self' data:; "
                "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; "
                "frame-ancestors 'none'")

    def deliver(self, text):
        result = self.ceo.deliver(text)
        t = threading.Thread(target=self._refresh_quietly, daemon=True)
        self._refreshers = [x for x in self._refreshers if x.is_alive()] + [t]
        t.start()
        return result

    def sohbet_ilet(self, text, prefix=transcript.CHAT_PREFIX):
        """A chat message from the owner -> the CEO (delivered or queued): the one path of the page's POST /api/chat and
        the Jarvis gate's is-ekle (prefix transcript.JARVIS_PREFIX). Only the server writes the prefix line; the
        text after it stays the owner's words. Raises ceo.CeoUnavailable."""
        return self.deliver(prefix + text)

    def answer_decision(self, note, answer, after=None):
        """The owner's answer to a pending decision card -> (HTTP status, JSON body): the one path of the page's POST
        /api/answer and the Jarvis gate's karar-cevapla. 400 invalid note name, 404 no such note, 409 already answered
        or already sent (kod cevap-iletildi) or CEO unreachable, 202 {status} delivered or queued. `after()` runs under
        the answer lock right after a successful delivery was recorded (the Jarvis gate marks its channel there)."""
        status = state_mod.decision_status(self.vault_ofis, note)
        if status == "invalid":
            return 400, {"error": "invalid note name"}
        if status == "missing":
            return 404, {"error": "no such decision note"}
        if status == "not_pending":
            return 409, {"error": ANSWERED_TEXT, "kod": ANSWERED_CODE}
        answers = self.answers
        with answers.lock:
            if note in answers.notes():
                return 409, {"error": ALREADY_SENT_TEXT, "kod": ANSWERED_CODE}
            try:
                result = self.deliver(f"{transcript.ANSWER_PREFIX}{note}\n{answer}")
            except ceo_mod.CeoUnavailable as e:
                return 409, {"error": f"CEO session unreachable: {e}"}
            answers.add(note)  # recorded before the page hears back: a quick second click is refused
            if after is not None:
                try:
                    after()
                except Exception as e:  # noqa: BLE001 — the answer is delivered; only the channel mark is missing
                    print(f"ofis: after-answer step failed: {type(e).__name__}", file=sys.stderr)
        return 202, {"status": result}

    def join_refreshes(self, timeout=10):
        """Waits for the refresh threads deliver() started (a test cleans its temp durum/ only after them)."""
        for t in list(self._refreshers):
            t.join(timeout)

    def _refresh_quietly(self):
        try:
            self.hub.refresh()
        except Exception as e:
            print(f"ofis: refresh after delivery failed: {type(e).__name__}", file=sys.stderr)


class Handler(BaseHTTPRequestHandler):
    server_version = "Ofis"
    sys_version = ""
    app = None  # set by make_server

    def log_message(self, fmt, *args):
        if self.command != "GET" or not self.path.startswith("/api/"):
            sys.stderr.write("ofis: %s\n" % (fmt % args))

    # --- responses ---

    def _send(self, status, body, content_type, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, data):
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _error(self, status, message):
        self._json(status, {"error": message})

    def _host_ok(self):
        if self.headers.get("Host") in self.app.allowed_hosts():
            return True
        self._error(403, "host not allowed")
        return False

    # --- methods ---

    def do_GET(self):
        try:
            return self._get()
        except Exception as e:  # never drop the connection: a JSON 500 (headers not sent yet: the handlers send last)
            print(f"ofis: GET {urlsplit(self.path).path} failed: {type(e).__name__}", file=sys.stderr)
            try:
                self._error(500, "internal error")
            except OSError:
                pass

    def _get(self):
        if not self._host_ok():
            return
        path = urlsplit(self.path).path
        if path in jarvis.KART_YOLLARI or path == jarvis.YOL:
            return self._jarvis_get(path)
        if not self._no_bearer():
            return
        if path in ("/", "/index.html"):
            return self._index()
        if path == "/api/state":
            state, _ = self.app.hub.snapshot()
            return self._json(200, state)
        if path == "/api/chat":
            _, chat = self.app.hub.snapshot()
            return self._json(200, {"messages": chat})
        if path == "/api/events":
            return self._events()
        if path == "/api/ceo/adimlar":  # the Komuta masası: the CEO's last tool steps (names + safe targets only)
            return self._json(200, self.app.hub.ceo_steps())
        if path == "/api/ceo/turlar":  # the footer under each CEO reply: steps, jobs opened, cost (no text)
            return self._json(200, self.app.hub.ceo_turns())
        if path == "/api/task":
            note = (parse_qs(urlsplit(self.path).query).get("note") or [""])[0]
            detail = task_detail.task_detail(self.app.office.vault_ofis, note, durum_dir=self.app.office.durum_dir)
            return self._json(200, detail) if detail else self._error(404, "task note not found")
        # phase 7: the Raporlar and Kalite views read the vault on request (not part of the SSE state: they change
        # only when a group or a job finishes). Read-only; the group id is checked by rapor.valid_group.
        if path == "/api/raporlar":
            return self._json(200, {"raporlar": rapor.list_reports(self.app.office.vault_ofis)})
        if path == "/api/rapor":
            group = (parse_qs(urlsplit(self.path).query).get("grup") or [""])[0]
            if not rapor.valid_group(group):
                return self._error(400, "invalid group")
            report = rapor.read_report(self.app.office.vault_ofis, group)
            return self._json(200, report) if report else self._error(404, "report not found")
        if path == "/api/not-yolu":  # a [[note]] on the page -> its path under OFIS/ for an obsidian:// link
            query = parse_qs(urlsplit(self.path).query)
            found = notyolu.bul(self.app.office.vault_ofis, (query.get("ad") or [""])[0],
                                (query.get("tercih") or [""])[0])
            return self._json(200, found) if found else self._error(404, "note not found")
        if path == "/api/kalite":  # phase 8: with the model selection (mapping, pilots, open model cards)
            return self._json(200, {**karne.quality(self.app.office.vault_ofis),
                                    # the NPC chat usage (bin/npc_sohbet.py): counted in the office's totals, never
                                    # in the quality metrics — a question is not a job
                                    "npc_sohbet": npc_sohbet.kullanim_toplami(
                                        npc_sohbet.kullanimlar(self.app.office.durum_dir)),
                                    "model_secimi": model_secimi.page(self.app.cfg, self.app.office.durum_dir),
                                    # the reviewer scorecard in short (the İK card): rounds, confirmed findings
                                    "denetciler": denetci.summary(denetci.list_rounds(self.app.office.durum_dir))})
        if path == "/api/muhasebe":  # the Muhasebeci's card: day / month spending from the Karne rows + open jobs + NPC chat
            state, _ = self.app.hub.snapshot()
            tz = ((state or {}).get("sahne") or {}).get("saat_dilimi") or model_durum.yerel_saat_dilimi()
            return self._json(200, muhasebe.ozet(self.app.office.vault_ofis, (state or {}).get("board") or [], tz=tz,
                                                durum_dir=self.app.office.durum_dir))
        if path == "/api/idari":  # the İdari işler card: server start, limits, autostart, Obsidian access, log size
            return self._json(200, muhasebe.idari(self.app.cfg, self.app.office.sunucu, self.app.vault_problem))
        if path == "/api/arge":  # the Ar-Ge uzmanı's card: the last report's summary, suggestions, the free check
            return self._json(200, arge.sayfa(self.app.current_config(), self.app.office.durum_dir))
        if path == "/api/kullanim":  # the limit pill's popup: windows, reset times, who used most (bin/kullanim.py)
            return self._json(200, self.app.kullanim.sayfa(self.app.current_config()))
        if path == "/api/sistem":  # the Sunucu odası: computer status (group totals only), suggestions, domains
            return self._json(200, self.app.sistem.durum(sayfa_acik=self.app.page_open()))
        if path == "/api/ayarlar":  # the Ayarlar tab: office name, projects with trust and open jobs, the rules
            self.app.ayarlari_yenile()
            return self._json(200, ayarlar.ozet(self.app.cfg, self.app.office.durum_dir))
        if path == "/api/usage":
            project = (parse_qs(urlsplit(self.path).query).get("project") or [""])[0]
            detail = self.app.hub.usage_detail(project) if launch.PROJECT_NAME.fullmatch(project) else None
            return self._json(200, detail) if detail else self._error(404, "unknown project")
        if path.startswith("/api/"):
            return self._error(404, "not found")
        return self._static(path)

    def do_POST(self):
        if not self._host_ok():
            return
        if urlsplit(self.path).path == jarvis.YOL:
            try:
                return self._jarvis_post()
            except Exception as e:  # never drop the connection: a JSON-RPC internal error
                print(f"ofis: POST {jarvis.YOL} failed: {type(e).__name__}", file=sys.stderr)
                try:
                    return self._json(200, jarvis.cevap(None, error=jarvis.hata(jarvis.INTERNAL, "internal error")))
                except OSError:
                    return
        if not self._no_bearer():
            return
        if self.headers.get("Origin") not in self.app.allowed_origins():
            return self._error(403, "origin not allowed")
        given = (self.headers.get("X-Ofis-Token") or "").encode()
        if not hmac.compare_digest(given, self.app.page_nonce.encode()):
            return self._error(403, "invalid token")
        if self.headers.get("Content-Type") is None or self.headers.get_content_type() != "application/json":
            return self._error(415, "content type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._error(411, "content length required")
        if length < 0:
            return self._error(400, "invalid content length")
        path = urlsplit(self.path).path
        # the Yakala box carries a small file in base64: its own limit from ofis.json yakala.dosya_mb (bin/yakala.py)
        limit = yakala.govde_siniri(self.app.current_config()) if path == "/api/yakala" else MAX_BODY
        if length > limit:
            return self._error(413, "body too large")
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._error(400, "invalid JSON")
        if not isinstance(body, dict):
            return self._error(400, "JSON object expected")
        if path == "/api/chat":
            return self._post_chat(body)
        if path == "/api/answer":
            return self._post_answer(body)
        if path == "/api/duyuru":  # The owner's announcement to every office session (bin/duyuru.py)
            return self._post_duyuru(body)
        if path == "/api/yakala":  # The owner's captured link or file -> one Ar-Ge research job (bin/yakala.py)
            return self._post_yakala(body)
        if path == "/api/ayarlar":  # the Ayarlar tab: add / change / remove a project, the office name
            return self._post_ayarlar(body)
        if path == "/api/npc-sohbet":  # a staff character answers a short question (bin/npc_sohbet.py)
            return self._post_npc_sohbet(body)
        return self._error(404, "not found")

    def _no_bearer(self):
        """The page's endpoints never take an Authorization header: the Jarvis key opens /a2a only."""
        if self.headers.get("Authorization") is None:
            return True
        self._error(403, "Authorization is not accepted here")
        return False

    # --- the Jarvis gate (bin/jarvis.py) ---

    def _peer(self):
        return self.client_address[0] if self.client_address else ""

    def _jarvis_open(self):
        """The gate's settings when this request may use it, else None after an error response: 404 while the gate
        is off (nothing tells it exists), 403 for a non-loopback peer or any Origin header (a browser)."""
        settings = self.app.jarvis.ayar()
        if settings is None:
            self._error(404, "not found")
            return None
        if not jarvis.yerel_mi(self._peer()):
            self._error(403, "loopback only")
            return None
        if self.headers.get("Origin") is not None:
            self._error(403, "browser requests are not accepted")
            return None
        return settings

    def _jarvis_get(self, path):
        settings = self._jarvis_open()
        if settings is None:
            return
        if path == jarvis.YOL:
            return self._error(405, "use POST")
        self._json(200, jarvis.kart(self.app.port, settings["kapsam"], self.app.cfg))

    def _jarvis_post(self):
        gate = self.app.jarvis
        settings = self._jarvis_open()
        if settings is None:
            return
        if not gate.sinir.izin(settings["dakika_sinir"]):
            return self._send(429, json.dumps({"error": "too many requests"}).encode(),
                              "application/json; charset=utf-8", {"Retry-After": "60"})
        if not gate.yetkili(self.headers.get("Authorization")):
            return self._send(401, json.dumps({"error": "invalid or missing bearer key"}).encode(),
                              "application/json; charset=utf-8", {"WWW-Authenticate": 'Bearer realm="ofis-jarvis"'})
        if self.headers.get("Content-Type") is None or self.headers.get_content_type() != "application/json":
            return self._error(415, "content type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._error(411, "content length required")
        if length < 0:
            return self._error(400, "invalid content length")
        if length > MAX_BODY:
            return self._error(413, "body too large")
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._json(200, jarvis.cevap(None, error=jarvis.hata(jarvis.PARSE_ERROR, "JSON okunamadı.")))
        self._json(200, gate.rpc(body, self.headers.get("A2A-Version"), settings))

    def _method_not_allowed(self):
        if self._host_ok():
            self._error(405, "method not allowed")

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _method_not_allowed

    # --- handlers ---

    @staticmethod
    def _text(value):
        if not isinstance(value, str) or not value.strip():
            return None, "text must be a non-empty string"
        if len(value) > MAX_TEXT:
            return None, f"text is limited to {MAX_TEXT} characters"
        return value.strip(), None

    def _deliver(self, text):
        try:
            result = self.app.sohbet_ilet(text)
        except ceo_mod.CeoUnavailable as e:
            self._error(409, f"CEO session unreachable: {e}")
            return False
        self._json(202, {"status": result})
        return True

    def _post_chat(self, body):
        text, err = self._text(body.get("text"))
        if err:
            return self._error(400, err)
        self._deliver(text)

    def _post_answer(self, body):
        answer, err = self._text(body.get("answer"))
        if err:
            return self._error(400, err)
        code, data = self.app.answer_decision(body.get("note"), answer)
        self._json(code, data)

    def _post_duyuru(self, body):
        """{metin, sure}: records the announcement and queues it for every active session; the post office delivers it
        and tells the CEO once. 202 {duyuru, hedef, not, bitis}; 400 on a bad text or duration."""
        sure = body.get("sure", "simdi")
        if sure is not None and not isinstance(sure, str):
            return self._error(400, "sure must be a string")
        try:
            result = duyuru.create(self.app.cfg, self.app.office.durum_dir, body.get("metin"), sure or "simdi",
                                   kaynak="sayfa")
        except duyuru.Refused as e:
            return self._error(400, str(e))
        except (OSError, jobs.JobError) as e:
            return self._error(500, f"duyuru kaydedilemedi: {type(e).__name__}")
        t = threading.Thread(target=self.app._refresh_quietly, daemon=True)
        self.app._refreshers = [x for x in self.app._refreshers if x.is_alive()] + [t]
        t.start()
        self._json(202, result)

    def _post_ayarlar(self, body):
        """{islem: proje-ekle|proje-guncelle|proje-sil|genel, …} (bin/ayarlar.py islem): 200 {tamam, islem, ad, guven,
        ipucu, ayarlar}; 400 invalid (error + hatalar + alanlar: each error's form field), 404 unknown project, 409 a delete that must wait / no config
        file, 500 the file could not be written."""
        try:
            code, data = self.app.ayar_degistir(body)
        except Exception as e:  # noqa: BLE001 — do_POST has no catch-all: never drop the connection
            print(f"ofis: POST /api/ayarlar failed: {type(e).__name__}", file=sys.stderr)
            code, data = 500, {"error": "internal error", "hatalar": ["internal error"], "alanlar": [""]}
        self._json(code, data)

    def _post_npc_sohbet(self, body):
        """{npc: <role key>, soru: <text>}: one tool-less model call over the office's own state (bin/npc_sohbet.py).
        200 {cevap, unvan, kullanim}; 400 bad role / question, 409 off or busy, 429 over the hourly limit (Retry-After),
        502 the call failed. Blocks only this request's thread (the server is threaded) for at most ~60 s."""
        try:
            if body.get("soru") is not None and not isinstance(body.get("soru"), str):
                return self._error(400, "soru must be a string")
            result = self.app.npc_sohbet.sor(body.get("npc"), body.get("soru"))
        except (npc_sohbet.Kapali, npc_sohbet.Gecersiz, npc_sohbet.Mesgul, npc_sohbet.Sinir,
                npc_sohbet.CagriHatasi) as e:
            code, data, extra = npc_sohbet.hata_json(e, self.app.cfg)
            return self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8",
                              extra)
        except Exception as e:  # noqa: BLE001 — do_POST has no catch-all: never drop the connection
            print(f"ofis: POST /api/npc-sohbet failed: {type(e).__name__}", file=sys.stderr)
            return self._error(500, "internal error")
        self._json(200, result)

    def _post_yakala(self, body):
        """{url, not} or {dosya_adi, dosya (base64), not}: validated and stored under durum/yakala/<id>/, and its one
        Ar-Ge job added through the path of `ekle` (a full queue is retried by the server). 202 {yakala, durum, is,
        hata, …}; 400 on bad input, 409 when the box is off, 429 over the hourly limit."""
        for key in ("url", "not", "dosya_adi", "dosya"):
            if body.get(key) is not None and not isinstance(body.get(key), str):
                return self._error(400, f"{key} must be a string")
        cfg = self.app.current_config()
        if yakala.ayar(cfg) is None:
            return self._error(409, "Yakala kapalı (ofis.json yakala.acik)")
        try:
            result = yakala.olustur(cfg, self.app.office.durum_dir, url=body.get("url"), not_=body.get("not"),
                                    dosya_adi=body.get("dosya_adi"), dosya_verisi=body.get("dosya"), kaynak="sayfa",
                                    add=self.app.postoffice._add_job,
                                    log=lambda line: print(line, file=sys.stderr, flush=True))
        except yakala.Sinir as e:
            return self._error(429, str(e))
        except yakala.Refused as e:
            return self._error(400, str(e))
        except (OSError, jobs.JobError) as e:
            return self._error(500, f"yakalanamadı: {type(e).__name__}")
        t = threading.Thread(target=self.app._refresh_quietly, daemon=True)
        self.app._refreshers = [x for x in self.app._refreshers if x.is_alive()] + [t]
        t.start()
        self._json(202, result)

    def _index(self):
        try:
            html = self.app.index_html()
        except OSError:
            return self._error(404, "not found")
        self._send(200, html.encode("utf-8"), TYPES[".html"], {"Content-Security-Policy": self.app.csp(html)})

    def _static(self, path):
        rel = unquote(path).lstrip("/")
        parts = rel.split("/")
        if not rel or "\x00" in rel or "\\" in rel or any(p in ("", ".", "..") or p.startswith(".") for p in parts):
            return self._error(404, "not found")
        full = os.path.realpath(os.path.join(self.app.web_dir, rel))
        if os.path.commonpath([full, self.app.web_dir]) != self.app.web_dir or not os.path.isfile(full):
            return self._error(404, "not found")  # also covers directories: no listing
        ctype = TYPES.get(os.path.splitext(full)[1].lower())
        if ctype is None:
            return self._error(404, "not found")
        with open(full, "rb") as f:
            data = f.read()
        self._send(200, data, ctype)

    def _events(self):
        hub = self.app.hub
        try:
            hub.snapshot()
        except Exception as e:
            print(f"ofis: initial snapshot failed: {type(e).__name__}", file=sys.stderr)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        sent_state = sent_chat = -1
        last_beat = time.monotonic()
        with hub.cond:
            hub.subscribers += 1
        try:
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.flush()
            while not self.app.stop_event.is_set():
                with hub.cond:
                    if hub.state_version == sent_state and hub.chat_version == sent_chat:
                        hub.cond.wait(timeout=1.0)
                    state, chat = hub.state, hub.chat
                    sv, cv = hub.state_version, hub.chat_version
                hub.touch()
                out = b""
                if sv != sent_state and state is not None:
                    out += b"event: state\ndata: " + json.dumps(state, ensure_ascii=False).encode() + b"\n\n"
                    sent_state = sv
                if cv != sent_chat:
                    payload = json.dumps({"messages": chat}, ensure_ascii=False).encode()
                    out += b"event: chat\ndata: " + payload + b"\n\n"
                    sent_chat = cv
                if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
                    out += b": heartbeat\n\n"
                    last_beat = time.monotonic()
                if out:
                    self.wfile.write(out)
                    self.wfile.flush()
        except OSError:
            pass  # client went away
        finally:
            with hub.cond:
                hub.subscribers -= 1
            self.close_connection = True


class AlreadyRunning(Exception):
    """Another Ofis server holds durum/server.lock."""


def acquire_lock(durum_dir):
    """Exclusive, non-blocking flock on durum/server.lock, held for the life of the returned file object.

    Two servers would each run a queue drainer and could deliver the same queued message twice; the second one
    must stop instead of taking the next free port."""
    os.makedirs(durum_dir, exist_ok=True)
    f = open(os.path.join(durum_dir, "server.lock"), "a+")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        f.close()
        raise AlreadyRunning("Ofis server already running (durum/server.lock is held)") from e
    f.seek(0)
    f.truncate()
    f.write(f"{os.getpid()}\n")
    f.flush()
    return f


def make_server(app, ports=PORTS):
    handler = type("OfisHandler", (Handler,), {"app": app})
    last_error = None
    for port in ports:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        except OSError as e:
            last_error = e
            continue
        httpd.daemon_threads = True
        app.port = httpd.server_address[1]
        return httpd
    raise OSError(f"no free port in {ports[0]}-{ports[-1]}: {last_error}")


def vault_problem(cfg):
    """A Turkish error line when the vault's OFIS folder cannot be read, else None. Started by launchd at login
    (bin/autostart.py), python may be refused ~/Documents by macOS privacy (TCC): "Operation not permitted"."""
    folder = os.path.expanduser(cfg["vault_ofis"])
    try:
        os.listdir(folder)
        return None
    except OSError as e:
        reason = e.strerror or type(e).__name__
    python = os.path.realpath(sys.executable)
    return (f"{autostart.VAULT_ERROR} notlarına erişilemiyor ({folder}): {reason}. Sunucu açık kalır ama işler, "
            "kararlar ve notlar okunamaz. macOS izin vermiyorsa: Sistem Ayarları > Gizlilik ve Güvenlik > Tam Disk "
            f"Erişimi'ne {python} ekleyin (ya da Dosyalar ve Klasörler'de Belgeler iznini verin), sonra sunucuyu "
            "yeniden başlatın.")


LOG_FILE = os.path.join(autostart.LOG_DIR, autostart.LOG_NAME)  # the launchd log (bin/autostart.py's plist)
LOG_LIMIT = 5 * 1024 * 1024  # rotate above this size
LOG_KEEP = 1024 * 1024  # this much of the end is kept in server.log.1
LOG_CHECK_SECONDS = 300.0


class LogRotator:
    """Size-based rotation of the launchd log (stdout/stderr redirected to LOG_FILE by bin/autostart.py's plist).

    launchd keeps its own O_APPEND handle on the file, so the file is never renamed or deleted: its last `keep` bytes
    (from a line start) are copied to `<log>.1` (replaced atomically), then the file is truncated in place; the next
    O_APPEND write lands at the new end. The start lines (START_MARKER, the port line, a vault error) are written back
    so `autostart.py status` still reads the latest start. Acts only when stdout is that very file (same device and
    inode) and was opened with O_APPEND (else a truncation would leave a hole up to the old offset); never touches any
    other path. A line written between the copy and the truncation can be lost (rare, a few bytes)."""

    def __init__(self, path=LOG_FILE, limit=LOG_LIMIT, keep=LOG_KEEP, stream=None):
        self.path = path
        self.limit = limit
        self.keep = keep
        self.stream = stream
        self.header = []  # the start lines, written back after a rotation

    def remember(self, line):
        self.header.append(line)

    def applies(self):
        stream = self.stream if self.stream is not None else sys.stdout
        try:
            fd = stream.fileno()
            st, log = os.fstat(fd), os.stat(self.path)
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        except (OSError, ValueError, AttributeError):  # io.UnsupportedOperation is an OSError
            return False
        return (st.st_dev, st.st_ino) == (log.st_dev, log.st_ino) and bool(flags & os.O_APPEND)

    def check(self):
        """Rotates when the file is over the limit; True when it did."""
        try:
            if not self.applies() or os.path.getsize(self.path) <= self.limit:
                return False
            with open(self.path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - self.keep))
                tail = f.read(self.keep)
            if size > self.keep:
                cut = tail.find(b"\n")
                tail = tail[cut + 1:] if cut >= 0 else tail
            old = self.path + ".1"
            tmp = self.path + ".1.tmp"
            with open(tmp, "wb") as f:
                f.write(tail)
            os.replace(tmp, old)
            os.truncate(self.path, 0)
            stream = self.stream if self.stream is not None else sys.stdout
            stream.flush()
            lines = self.header + [f"ofis: günlük {size} bayttı; son kısmı {os.path.basename(old)} dosyasında"]
            stream.write("".join(line + "\n" for line in lines))
            stream.flush()
            return True
        except OSError as e:
            print(f"ofis: günlük döndürülemedi: {e}", file=sys.stderr, flush=True)
            return False

    def run(self, stop_event, interval=LOG_CHECK_SECONDS):
        while not stop_event.wait(interval):
            self.check()


def main(durum_dir=DURUM_DIR):
    if yasaklar.test_ortami_var():  # the test-only config override (bin/yasaklar.py): never under the live office
        print("ofis: OFIS_TEST / OFIS_CONFIG ayarlı: bunlar yalnız testler içindir, ofis bu ortamla başlamaz. "
              "Bu değişkenleri kaldırıp yeniden başlatın.", file=sys.stderr, flush=True)
        return 1
    rotator = LogRotator()
    rotator.remember(f"{autostart.START_MARKER} (pid {os.getpid()})")
    print(rotator.header[0], file=sys.stderr, flush=True)
    try:
        lock = acquire_lock(durum_dir)
    except AlreadyRunning as e:
        # exit 0: under launchd (KeepAlive SuccessfulExit=false) a second server must not be restarted in a loop
        print(f"ofis: {e}; bu süreç kapanıyor", file=sys.stderr, flush=True)
        return 0
    try:
        cfg = launch.load()
    except launch.Refused as e:  # no ofis.json yet (first start) or not an object: a plain line, no traceback
        print(f"ofis: {e}", file=sys.stderr, flush=True)
        return 1
    akis.announce(durum_dir)  # this process runs workflows (`ofis.py akis` checks it, bin/akis.py)
    try:  # review panel snapshots a killed server left behind (bin/denetci.py)
        for folder in denetci.sweep(cfg):
            rotator.remember(f"ofis: eski denetçi kopyası silindi: {folder}")
    except Exception as e:  # never stops the start
        rotator.remember(f"ofis: denetçi kopyası temizliği yapılamadı: {type(e).__name__}: {e}")
    # the vault's error and event record (bin/olaylar.py): errors only, never the request lines
    events = olaylar.Olaylar(os.path.expanduser(cfg["vault_ofis"]))
    problem = vault_problem(cfg)
    if problem:
        rotator.remember(problem)
        print(problem, file=sys.stderr, flush=True)
        events.record("obsidian", problem)
    # phase 8: config_path = the tier overrides cevapla writes; the post office's log lines pass through the record
    app = App(cfg, config_path=launch.config_path(), log=events.stream(sys.stderr))
    # structured for the İdari işler card: never the line's free text (it names the vault's home path)
    app.vault_problem = {"sorun": True, "python": os.path.realpath(sys.executable)} if problem else None
    app.hub.events = events
    app.office.olaylar = events  # the newest rows of the error record ride along in /api/state (the doctor's card)
    events.watch("ceo", "teslim", lambda: app.ceo.last_error)
    app.ceo.olay = lambda text: events.record("ceo", text)  # CEO session rotations (bin/ceo.py)
    events.watch("projeler", "teslim", app.postoffice.delivery_errors)  # errors and launch warnings per session
    httpd = make_server(app)
    app.start_threads()
    rotator.remember(f"Ofis: http://127.0.0.1:{app.port}")
    print(rotator.header[-1], flush=True)
    events.record("başlangıç", f"sunucu başladı (pid {os.getpid()}, port {app.port})")
    for target in (rotator.run, events.run):
        threading.Thread(target=target, args=(app.stop_event,), daemon=True).start()
    # the Sunucu odası: computer samples while the page is watched; the projects' domains a few times a day
    threading.Thread(target=app.sistem.run, args=(app.stop_event,), daemon=True,
                     kwargs={"izleniyor": app.page_watched, "sayfa_acik": app.page_open}).start()

    def domain_log(line):
        print(line, file=sys.stderr, flush=True)
        events.record(olaylar.kind_of_background_line(line), line)  # a measurement line is no error
    domains = sistem.DomainKontrol(app.current_config, app.office.durum_dir, app.ceo, log=domain_log)
    threading.Thread(target=domains.run, args=(app.stop_event,), daemon=True).start()
    # the project sorumlusu notes OFIS/Projeler/<proje>.md (bin/sorumlu.py): rewritten only when their text changes
    notlar = sorumlu.ProjeNotlari(app.current_config, app.office.durum_dir, log=domain_log)
    threading.Thread(target=notlar.run, args=(app.stop_event,), daemon=True).start()
    # the morning summary OFIS/Ozetler/YYYY-MM-DD.md and its one CEO notice (bin/ozet.py; ofis.json sabah_ozeti)
    sabah = ozet.SabahOzeti(app.current_config, app.office.durum_dir, app.ceo, log=domain_log,
                            oneriler=lambda: [o.get("metin") for o in (app.sistem.durum().get("oneriler") or [])
                                              if isinstance(o, dict)])
    threading.Thread(target=sabah.run, args=(app.stop_event,), daemon=True).start()
    # the memory health check OFIS/Saglik/Saglik-YYYY-MM-DD.md (bin/hafiza_saglik.py; ofis.json hafiza_saglik): reads
    # OFIS notes only, never changes one; a notice only when there are new problems
    import hafiza_saglik
    saglik = hafiza_saglik.HafizaSaglik(app.current_config, app.office.durum_dir, app.ceo, log=domain_log)
    threading.Thread(target=saglik.run, args=(app.stop_event,), daemon=True).start()
    # the end-of-day review (bin/gunsonu.py; ofis.json gun_sonu): once a day inside its evening window the measurement,
    # the note OFIS/GunSonu/GunSonu-YYYY-MM-DD.md and one notice; on a bad day one review job (the path of `ekle`) whose
    # suggestions are written into the note with a second notice
    gun_sonu = gunsonu.GunSonu(app.current_config, app.office.durum_dir, app.ceo, add=app.postoffice._add_job,
                               olaylar=events, log=domain_log)
    threading.Thread(target=gun_sonu.run, args=(app.stop_event,), daemon=True).start()
    # the Yakala inbox (bin/yakala.py; ofis.json yakala): retries a refused job add, and once a research job is final
    # writes OFIS/ArGe/Yakala-… and sends its one notice
    yakalayici = yakala.Yakala(app.current_config, app.office.durum_dir, app.ceo, add=app.postoffice._add_job,
                               log=domain_log)
    threading.Thread(target=yakalayici.run, args=(app.stop_event,), daemon=True).start()
    # the prompt audit (bin/talimat_denetimi.py; ofis.json talimat_denetimi): when the permanent model mapping changes,
    # one read-only Ar-Ge job audits the instructions; its note OFIS/ArGe/TalimatDenetimi-…, one card and one notice
    talimat = talimat_denetimi.TalimatDenetimi(app.current_config, app.office.durum_dir, app.ceo,
                                               add=app.postoffice._add_job, log=domain_log)
    threading.Thread(target=talimat.run, args=(app.stop_event,), daemon=True).start()
    # The owner's Claude plan usage limits (bin/limitler.py; ofis.json limitler): reads ~/.claude/ofis/limitler.json only;
    # one CEO notice per window and threshold (80 %, 95 %), never pauses anything
    import limitler
    limit_uyarisi = limitler.LimitUyarisi(app.current_config, app.office.durum_dir, app.ceo, log=domain_log)
    threading.Thread(target=limit_uyarisi.run, args=(app.stop_event,), daemon=True).start()
    # the Ar-Ge odası (bin/arge.py): the free daily check (opencode models diff, CLI versions; never beside a Kontrol or
    # a review) and the reports of arge jobs whose Kontrol finished
    po = app.postoffice

    def agir_is():
        return bool(po.kontrol.running or po.codex.running or po.mudur.running)
    argecek = arge.GunlukKontrol(app.current_config, app.office.durum_dir, mesgul=agir_is, log=domain_log,
                                 ceo=app.ceo)
    threading.Thread(target=argecek.run, args=(app.stop_event,), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception as e:  # a crash of the server loop is recorded, then launchd restarts the server
        events.record("çöküş", f"sunucu çöktü: {type(e).__name__}: {e}")
        raise
    finally:
        app.stop_event.set()
        events.flush(force=True)
        httpd.server_close()
        lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
