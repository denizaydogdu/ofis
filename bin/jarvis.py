"""The Jarvis gate: an A2A-compatible door for Jarvis (the owner's local macOS menu-bar app, an A2A client). Two scopes
(ofis.json jarvis.kapsam, owner decision 2026-11-14): "durum-karar" = the office status, the project list, the pending
decisions and answering one of them; "durum-karar-is" = the same plus `is-ekle`: the owner's spoken request for new work,
delivered to the CEO as a top-level `[Sahip · Jarvis]` prompt through the page chat's own path (App.sohbet_ilet). The
gate never adds a job itself and never chats: the CEO handles the request like a page message.

    GET  /.well-known/agent-card.json   the Agent Card (also /.well-known/agent.json for older clients)
    POST /a2a                           JSON-RPC 2.0, `Authorization: Bearer <durum/jarvis_anahtari>`

Protocol: A2A 1.0 (JSON-RPC binding: `SendMessage`, `GetTask`; parts `{"text"}` / `{"data"}`; roles `ROLE_USER` /
`ROLE_AGENT`; states `TASK_STATE_*`) and, for clients built on the widely used 0.3 shapes, the same calls as
`message/send` / `tasks/get` with `kind` discriminators, roles `user` / `agent` and states `completed`,
`input-required`, … — the method name picks the dialect of the answer. Streaming, push notifications, task lists and
cancelling are not offered (UnsupportedOperationError -32004 / TaskNotCancelableError -32002); a task is final when
its answer comes back, except input-required.

The skill is chosen by `metadata.skill` (of the message or of params), a data part's `skill` field, or a text part
that is exactly a skill id. Free text is never interpreted (no chat): it is rejected.

Security (docs/gelistirici/guvenlik.md "The Jarvis gate"): ofis.json `jarvis: {acik, kapsam, dakika_sinir,
is_saatlik_sinir}` (off or an unknown kapsam = every Jarvis path is 404); loopback peers and the server's own Host only; no Origin header (a browser
never reaches it); the key in `durum/jarvis_anahtari` (0600, created atomically, never logged, never in /api/state),
compared in constant time; at most `dakika_sinir` requests a minute; the page token is not accepted here and the
Jarvis key is not accepted on the page's endpoints (server.py refuses any Authorization header there).

An answer goes through exactly the page's path (server.App.answer_decision: the same checks, the same AnswerLog, the
same `[Sahip · karar cevabı] <note>` prompt to the CEO). A high-risk card (`risk_sinifla`) needs `ekran_onayi: true` —
Jarvis collects it with an on-screen button, never by voice — else the task is input-required. After a delivery the
note gets `cevap_kanali: Jarvis üzerinden` and the server log one line. The same answer again → completed with
`zaten_iletildi`, no second delivery. Tasks live in memory for this run only (tasks/get after a restart: not found).

`is-ekle` needs `dugme_onayi: true` (Jarvis's on-screen "Gönder" button; never voice alone), a non-empty text of at
most MAX_METIN characters in one data part, and an empty or registered project name; at most `is_saatlik_sinir`
deliveries an hour. Delivered message ids are kept in durum/jarvis/is_ekle.json (hashes only, never the text), so the
same messageId is never delivered twice, also after a restart."""
import collections
import hashlib
import hmac
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone

import budget
import ceo as ceo_mod
import danisman
import jobs
import launch
import model_durum
import model_secimi
import mudur
import sahip
import muhasebe
import state as state_mod
import transcript

KEY = "jarvis"
KAPSAM = "durum-karar"  # scope 2: status, projects, decisions
KAPSAM_IS = "durum-karar-is"  # scope 3 (owner decision 2026-11-14): scope 2 + is-ekle
KAPSAMLAR = (KAPSAM, KAPSAM_IS)
DEFAULT_IS_SINIR = 10
MAX_IS_SINIR = 100
DEFAULT_SINIR = 60
MAX_SINIR = 600
ANAHTAR_DOSYASI = "jarvis_anahtari"
YOL = "/a2a"
KART_YOLLARI = ("/.well-known/agent-card.json", "/.well-known/agent.json")
KAYIT = os.path.join("jarvis", "cevaplar.json")  # durum/jarvis/cevaplar.json: what Jarvis delivered (hashes only)
KANAL_ALANI = "cevap_kanali"
KANAL = "Jarvis üzerinden"
IS_EKLE = "is-ekle"
SKILLS = ("durum", "projeler", "kararlar", "karar-cevapla", IS_EKLE)
TEMEL_SKILLS = SKILLS[:-1]
ARG_ALANLARI = ("note", "cevap", "ekran_onayi", "proje", "metin", "dugme_onayi")
IS_KAYIT = os.path.join("jarvis", "is_ekle.json")  # durum/jarvis/is_ekle.json: delivered is-ekle messages (hashes)
MAX_METIN = 2000
MAX_ACIKLAMA = 200
AJAN_SURUMU = "1.0.0"
MAX_TASKS = 200
MAX_KAYIT = 500
MAX_SORU = 300
MAX_CEVAP = 4000  # server.MAX_TEXT
MAX_ID = 128

# --- configuration ---


def _tamsayi(value, default, top):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= top:
        return default
    return value


def ayar(cfg):
    """{acik, kapsam, dakika_sinir, is_saatlik_sinir} when the gate is on, else None (missing key, `acik` not true, or
    a kapsam other than "durum-karar" / "durum-karar-is": the gate is off rather than wider than approved)."""
    raw = cfg.get(KEY) if isinstance(cfg, dict) else None
    if not isinstance(raw, dict) or raw.get("acik") is not True:
        return None
    kapsam = raw.get("kapsam", KAPSAM)
    if kapsam not in KAPSAMLAR:
        return None
    return {"acik": True, "kapsam": kapsam,
            "dakika_sinir": _tamsayi(raw.get("dakika_sinir", DEFAULT_SINIR), DEFAULT_SINIR, MAX_SINIR),
            "is_saatlik_sinir": _tamsayi(raw.get("is_saatlik_sinir", DEFAULT_IS_SINIR), DEFAULT_IS_SINIR,
                                         MAX_IS_SINIR)}


def beceriler(kapsam):
    """The skill ids a scope offers."""
    return SKILLS if kapsam == KAPSAM_IS else TEMEL_SKILLS


def projeler(cfg):
    """[{ad, aciklama}] of the registered projects: the name and the first line of its description, no paths."""
    out = []
    for ad, p in sorted(((cfg or {}).get("projects") or {}).items()):
        if not isinstance(ad, str) or not launch.PROJECT_NAME.fullmatch(ad):
            continue
        desc = p.get("description") if isinstance(p, dict) else ""
        line = re.sub(r"\s+", " ", str(desc or "").strip().split("\n", 1)[0]).strip()
        out.append({"ad": ad, "aciklama": line[:MAX_ACIKLAMA] + ("…" if len(line) > MAX_ACIKLAMA else "")})
    return out


def yerel_mi(addr):
    """True for a loopback peer address (the server binds 127.0.0.1; checked anyway)."""
    a = str(addr or "")
    return a == "::1" or a.startswith("127.") or a.startswith("::ffff:127.")


class Sinir:
    """A sliding one-minute window over every request to /a2a (failed ones too: a key cannot be guessed fast)."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.times = collections.deque()
        self.lock = threading.Lock()

    def izin(self, limit):
        now = self.clock()
        with self.lock:
            while self.times and now - self.times[0] >= 60:
                self.times.popleft()
            if len(self.times) >= limit:
                return False
            self.times.append(now)
            return True


# --- the Agent Card ---


def kart(port, kapsam=KAPSAM, cfg=None):
    """The Agent Card; it lists `is-ekle` only when the scope allows it. The owner's name: cfg's (else ofis.json's)
    sahip_adi."""
    adi_in = sahip.in_(cfg)
    url = f"http://127.0.0.1:{port}{YOL}"
    io_modes = ["text/plain", "application/json"]
    beceriler_ = [
        {"id": "durum", "name": "Ofis durumu",
         "description": "Çalışan ve sıradaki işler (şu anki adımlarıyla), bekleyen karar sayısı, CEO'nun durumu ve "
                        "bugünkü kullanım: kısa Türkçe metin ve aynısı JSON olarak.",
         "tags": ["ofis", "durum"], "examples": ["durum"], "inputModes": io_modes, "outputModes": io_modes},
        {"id": "projeler", "name": "Projeler",
         "description": "Ofise bağlı projelerin adları ve tek satırlık açıklamaları.",
         "tags": ["ofis", "proje"], "examples": ["projeler"], "inputModes": io_modes, "outputModes": io_modes},
        {"id": "kararlar", "name": "Bekleyen kararlar",
         "description": f"{adi_in} cevabını bekleyen kararlar: not, başlık, proje, tür, kısa soru, seçenekler, risk ve "
                        "ekran onayı gerekip gerekmediği.",
         "tags": ["ofis", "karar"], "examples": ["kararlar"], "inputModes": io_modes, "outputModes": io_modes},
        {"id": "karar-cevapla", "name": "Karar cevapla",
         "description": f"Bekleyen bir karara {adi_in} cevabı (seçenek kodu ya da metin), sayfadaki cevapla aynı yoldan "
                        "CEO'ya gider. Yüksek riskli kartta ekran_onayi: true şart. Veri parçası: "
                        "{skill: 'karar-cevapla', note, cevap, ekran_onayi}.",
         "tags": ["ofis", "karar", "cevap"],
         "examples": ['{"skill": "karar-cevapla", "note": "2026-11-14-ornek-uygulama-ceo-sorusu.md", "cevap": "A", '
                      '"ekran_onayi": false}'],
         "inputModes": ["application/json"], "outputModes": io_modes},
    ]
    if kapsam == KAPSAM_IS:
        beceriler_.append(
            {"id": IS_EKLE, "name": "Ofise iş ver",
             "description": f"{adi_in} sesle söylediği yeni iş isteği, sayfadaki sohbetle aynı yoldan CEO'ya gider "
                            f"('{sahip.JARVIS_PREFIX.strip()}'). İşi CEO açar; bu beceri iş eklemez. Ekrandaki Gönder düğmesi şart: "
                            "dugme_onayi: true. Veri parçası: {skill: 'is-ekle', proje, metin, dugme_onayi}.",
             "tags": ["ofis", "is", "ceo"],
             "examples": ['{"skill": "is-ekle", "proje": "ornek-uygulama", "metin": "Giriş sayfasındaki hatayı düzelt", '
                          '"dugme_onayi": true}'],
             "inputModes": ["application/json"], "outputModes": io_modes})
        aciklama = (f"{adi_in} yerel ajan ofisi. Bu kapı durum, projeler, bekleyen kararlar, karar cevabı ve CEO'ya "
                    "yeni iş isteği içindir; serbest sohbet yoktur.")
    else:
        aciklama = (f"{adi_in} yerel ajan ofisi. Bu kapı yalnız durum, projeler, bekleyen kararlar ve karar cevabı "
                    "içindir; iş ekleme ve CEO sohbeti yoktur.")
    return {
        "name": "Ofis",
        "description": aciklama,
        # A2A 1.0
        "supportedInterfaces": [{"url": url, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"},
                                {"url": url, "protocolBinding": "JSONRPC", "protocolVersion": "0.3"}],
        "version": AJAN_SURUMU,
        "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False,
                         "stateTransitionHistory": False},
        # both shapes of the bearer scheme: 1.0's variant key and 0.3's OpenAPI fields
        "securitySchemes": {"bearer": {"httpAuthSecurityScheme": {"scheme": "Bearer"},
                                       "type": "http", "scheme": "bearer"}},
        "securityRequirements": [{"schemes": {"bearer": {"list": []}}}],
        "defaultInputModes": io_modes,
        "defaultOutputModes": io_modes,
        "skills": beceriler_,
        # A2A 0.3 (older clients)
        "protocolVersion": "0.3.0",
        "url": url,
        "preferredTransport": "JSONRPC",
        "security": [{"bearer": []}],
    }


# --- the risk rule ---

# the managers' owner-word lists (bin/mudur.py SAHIBE) that make an answer by voice too risky
RISK_KATEGORILERI = ("para ve bütçe", "commit, push ya da yayın", "silme")
EK_RISK = (
    ("zorla gönderme ya da geçmişi yeniden yazma", (
        "force*", "zorla*", "gecmisi yeniden yaz*", "gecmisini yeniden yaz*", "gecmisi degistir*",
        "gecmisini degistir*", "history rewrit*", "rewrite history", "rewrite the history", "rewriting history",
        "reset hard", "filter branch", "amend*", "squash*")),
    ("bütçe ya da çağrı sınırı artışı", (
        "cagri sinir*", "call limit*", "sinir artir*", "sinirini artir*", "sinirlari artir*", "limit artir*",
        "limiti artir*", "raise the limit", "increase the limit", "butce artir*", "butceyi artir*")),
    ("ofis.json değişikliği", ("ofis json",)),
)
_EK_RE = tuple((neden, mudur._derle(words)) for neden, words in EK_RISK)
_MUDUR_RE = tuple((neden, mudur._derle(words)) for neden, words in mudur.SAHIBE if neden in RISK_KATEGORILERI)
# cards whose plain yes writes ofis.json (the tier mapping or the advisor): model selection and the advisor pilot
OFIS_JSON_TURLERI = (model_secimi.PROPOSAL, model_secimi.RESULT) + tuple(danisman.DECISIONS)


def risk_sinifla(card):
    """("yuksek" | "normal", short Turkish reason) for a decision card (a /api/state decision or manager card).
    Deterministic: the card's own risk field, an open security finding, a kind that writes ofis.json, then the words
    of its title, question and options (folded like bin/mudur.py). Errs towards yuksek: a false alarm costs one
    on-screen tap, a miss lets a voice command push or delete."""
    card = card if isinstance(card, dict) else {}
    if card.get("risk") == "yuksek":
        return "yuksek", "kartın kendi risk seviyesi yüksek"
    if card.get("guvenlik_acik"):
        return "yuksek", "açık güvenlik bulgusu var"
    if card.get("kind") in OFIS_JSON_TURLERI:
        return "yuksek", "ofis.json değişikliği"
    parts = [str(card.get("title") or ""), str(card.get("question") or "")]
    parts += [str(o.get("metin") or "") for o in card.get("options") or [] if isinstance(o, dict)]
    framed = mudur.kelimeler("\n".join(parts))
    for neden, pattern in _EK_RE + _MUDUR_RE:
        if pattern.search(framed):
            return "yuksek", neden
    return "normal", ""


SECENEK = re.compile(r"\s*([A-Ea-e])\s*\)?\s*")


def secenek_cevabi(card, cevap):
    """(answer text, error). A bare option code ("A", "b", "C)") on a card with options becomes "A) <metin>" (what
    the page's option button sends); a code the card does not offer is an error; any other text stays as given."""
    options = [o for o in (card.get("options") or []) if isinstance(o, dict)]
    m = SECENEK.fullmatch(cevap)
    if not options or not m:
        return cevap, None
    kod = m.group(1).upper()
    for o in options:
        if o.get("kod") == kod:
            return f"{kod}) {str(o.get('metin') or '').strip()}", None
    return None, f"Bu kartta {kod} seçeneği yok."


# --- the skills' data ---

# the page's step labels (web/is-akisi.js): "<unvan> aldı", "<oda> çalışıyor"; the Genel Müdür is no step. The worker's
# title by model family lives in the page only: here the Ar-Ge uzmanı for the Ar-Ge desk, else a plain "çalışan".
ADIM = {"alindi": "CEO aldı", "kontrol": "Kontrol", "rapor": "rapor geldi", "ceo": "CEO'ya ulaştı",
        "iletildi": "sana iletildi"}
ARGE_PROJESI = "arge"  # bin/arge.py PROJE
BEKLEME = {"cevap": "senin cevabını bekliyor", "izin": "izin bekliyor"}
CEO_DURUMU = {"busy": "çalışıyor", "waiting": "izin bekliyor", "idle": "boşta", "dormant": "uykuda",
              "absent": "henüz başlamadı", "unknown": "bilinmiyor"}
CALISAN = ("baslatiliyor", "calisiyor", "karar-bekliyor", "incelemede", "kontrolde")


def _adim_etiketi(adim, durum, project):
    if adim == "verildi":
        unvan = "Ar-Ge uzmanı" if project == ARGE_PROJESI else "çalışan"
        return f"{unvan} işi alacak" if durum == "simdi" else f"{unvan} işi aldı"
    if adim == "calisiyor":
        oda = "Ar-Ge odasında" if project == ARGE_PROJESI else (f"{project} masasında" if project else "masasında")
        return f"{oda} çalışıyor"
    return ADIM.get(adim, "")


def _adim(task):
    """The job's current step from its progress line (state.is_yolu): {adim, etiket, not}."""
    yol = task.get("yol") or []
    cur = next((s for s in yol if s.get("durum") == "simdi"), None) or \
        next((s for s in yol if s.get("durum") == "hata"), None)
    if not cur:
        return {"adim": "", "etiket": "", "not": ""}
    etiket = _adim_etiketi(cur.get("adim"), cur.get("durum"), str(task.get("project") or "")[:40])
    note = cur.get("not") or ""
    return {"adim": cur.get("adim", ""), "etiket": etiket, "not": BEKLEME.get(note, note)}


def _usd(value):
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def durum_verisi(state, harcama, kararlar, projeler_=None):
    """The `durum` skill's data: only office names (job note names, project names), no paths, no session ids."""
    state = state or {}
    isler = []
    for t in state.get("tasks") or []:
        if t.get("status") not in CALISAN + ("sirada",):
            continue
        isler.append({"not": t.get("note", ""), "baslik": t.get("title", ""), "proje": t.get("project", ""),
                      "durum": t.get("status", ""), "adim": _adim(t), "harcanan_usd": _usd(t.get("spent")),
                      "butce_usd": _usd(t.get("budget"))})
    ceo = state.get("ceo") or {}
    ceo_usd = _usd(ceo.get("cost_today")) or 0.0
    ceo_tk = ceo.get("usage_today") if isinstance(ceo.get("usage_today"), int) else None
    isler_usd = _usd((harcama or {}).get("usd")) or 0.0
    isler_tk = (harcama or {}).get("token")
    toplam_tk = None if isler_tk is None and ceo_tk is None else (isler_tk or 0) + (ceo_tk or 0)
    return {
        "calisan": [i for i in isler if i["durum"] != "sirada"],
        "sirada": [i for i in isler if i["durum"] == "sirada"],
        "bekleyen_karar": len(kararlar),
        "yuksek_riskli_karar": sum(1 for k in kararlar if k["risk"] == "yuksek"),
        "ceo": {"durum": ceo.get("state", "unknown"), "etiket": CEO_DURUMU.get(ceo.get("state"), "bilinmiyor"),
                "kuyruk": ceo.get("queue", 0) if isinstance(ceo.get("queue"), int) else 0},
        "bugun": {"gun": state.get("today", ""), "isler_usd": isler_usd, "ceo_usd": ceo_usd,
                  "toplam_usd": round(isler_usd + ceo_usd, 4), "toplam_token": toplam_tk},
        # The owner's Claude plan usage limits (bin/limitler.py sayfa via /api/state.limitler); None when off / no data
        "limitler": _limitler(state.get("limitler")),
        "projeler": list(projeler_ or []),
    }


def _limitler(lim):
    if not isinstance(lim, dict) or not isinstance(lim.get("metin"), str):
        return None
    pencere = {k: {"yuzde": p.get("yuzde"), "sifirlanma": p.get("sifirlanma"), "gecti": bool(p.get("gecti"))}
               for k in ("haftalik", "bes_saat") for p in [lim.get(k)] if isinstance(p, dict)}
    return {**pencere, "olculdu": lim.get("olculdu"), "eski": bool(lim.get("eski")), "metin": lim["metin"]}


def durum_metni(d):
    calisan, sirada = d["calisan"], d["sirada"]
    lines = [f"Ofis durumu: {len(calisan)} iş çalışıyor, {len(sirada)} iş sırada."]
    for i in (calisan + sirada)[:8]:
        adim = i["adim"]
        step = adim["etiket"] + (f" ({adim['not']})" if adim["not"] else "") if adim["etiket"] else i["durum"]
        lines.append(f"- {i['proje']} — {i['baslik']}: {step}")
    if len(calisan) + len(sirada) > 8:
        lines.append(f"- … ve {len(calisan) + len(sirada) - 8} iş daha")
    karar = f"Bekleyen karar: {d['bekleyen_karar']}"
    if d["yuksek_riskli_karar"]:
        karar += f" ({d['yuksek_riskli_karar']} tanesi yüksek riskli)"
    lines.append(karar + ".")
    lines.append(f"CEO: {d['ceo']['etiket']}.")
    lines.append(f"Bugünkü kullanım: {budget.spend_text(d['bugun']['toplam_usd'], d['bugun']['toplam_token'])}.")
    if d.get("limitler"):
        lines.append(f"Claude kullanım sınırı: {d['limitler']['metin']}.")
    return "\n".join(lines)


def kart_verisi(card, sent, mudur_karti=False):
    risk, neden = risk_sinifla(card)
    soru = re.sub(r"\s+", " ", str(card.get("question") or "")).strip()
    return {"note": card.get("note", ""), "baslik": card.get("title", ""), "proje": card.get("project", ""),
            "tur": "mudur-karari" if mudur_karti else (card.get("kind") or "proje-sorusu"),
            "soru": soru[:MAX_SORU] + ("…" if len(soru) > MAX_SORU else ""),
            "secenekler": [{"kod": o.get("kod", ""), "metin": o.get("metin", "")} for o in card.get("options") or []
                           if isinstance(o, dict)],
            "risk": risk, "risk_nedeni": neden, "ekran_onayi_gerekir": risk == "yuksek",
            "soruldu": card.get("asked", ""), "cevap_iletildi": card.get("note") in sent}


def kararlar_metni(items):
    if not items:
        return "Bekleyen karar yok."
    lines = [f"Bekleyen {len(items)} karar:"]
    for k in items[:10]:
        extra = " · yüksek risk, ekranda onay gerekir" if k["risk"] == "yuksek" else ""
        sent = " · cevabın iletildi" if k["cevap_iletildi"] else ""
        lines.append(f"- {k['proje']} — {k['baslik']}{extra}{sent}")
    if len(items) > 10:
        lines.append(f"- … ve {len(items) - 10} karar daha")
    return "\n".join(lines)


# --- the A2A wire shapes ---

V1, V03 = "1.0", "0.3"
METHODS = {"SendMessage": ("send", V1), "message/send": ("send", V03),
           "GetTask": ("get", V1), "tasks/get": ("get", V03),
           "CancelTask": ("cancel", V1), "tasks/cancel": ("cancel", V03)}
UNSUPPORTED = ("SendStreamingMessage", "message/stream", "SubscribeToTask", "tasks/resubscribe", "ListTasks",
               "tasks/list", "GetExtendedAgentCard", "agent/getAuthenticatedExtendedCard",
               "CreateTaskPushNotificationConfig", "GetTaskPushNotificationConfig", "ListTaskPushNotificationConfig",
               "DeleteTaskPushNotificationConfig", "tasks/pushNotificationConfig/set",
               "tasks/pushNotificationConfig/get", "tasks/pushNotificationConfig/list",
               "tasks/pushNotificationConfig/delete")
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL = -32700, -32600, -32601, -32602, -32603
TASK_NOT_FOUND, NOT_CANCELABLE, UNSUPPORTED_OP, VERSION_NOT_SUPPORTED = -32001, -32002, -32004, -32009


def surum_destekli(value):
    """The A2A-Version header: none (0.3 assumed), 0.3.x or 1.x."""
    v = str(value or "").strip()
    return not v or v == "0.3" or v.startswith("0.3.") or v == "1" or v.startswith("1.")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parca(dialect, text=None, data=None):
    if text is not None:
        return {"kind": "text", "text": text} if dialect == V03 else {"text": text}
    return {"kind": "data", "data": data} if dialect == V03 else {"data": data, "mediaType": "application/json"}


def wire(task, dialect):
    """The task in the dialect's shape: the status message carries the text (and, unless completed, the reason as
    data); a completed task carries one artifact named after the skill with the text and the data."""
    state = task["state"] if dialect == V03 else "TASK_STATE_" + task["state"].upper().replace("-", "_")
    parts = [_parca(dialect, text=task["text"])]
    if task["state"] != "completed" and task["data"]:
        parts.append(_parca(dialect, data=task["data"]))
    msg = {"messageId": task["status_mid"], "role": "agent" if dialect == V03 else "ROLE_AGENT", "parts": parts,
           "taskId": task["id"], "contextId": task["contextId"]}
    out = {"id": task["id"], "contextId": task["contextId"],
           "status": {"state": state, "message": msg, "timestamp": task["timestamp"]},
           "artifacts": [], "metadata": {"skill": task["skill"]}}
    if task["state"] == "completed":
        out["artifacts"] = [{"artifactId": task["artifact_id"], "name": task["skill"],
                             "parts": [_parca(dialect, text=task["text"]), _parca(dialect, data=task["data"])]}]
    if dialect == V03:
        out["kind"] = "task"
        msg["kind"] = "message"
    return out


def cevap(rid, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    return out


def hata(code, message):
    return {"code": code, "message": message}


def _parcalar(parts):
    """(texts, datas) of a message's parts: text parts and data parts holding a JSON object, in either shape."""
    texts, datas = [], []
    for p in parts:
        if not isinstance(p, dict):
            continue
        if isinstance(p.get("text"), str):
            texts.append(p["text"])
        elif isinstance(p.get("data"), dict):
            datas.append(p["data"])
    return texts, datas


def _args(datas):
    args = {}
    for d in datas:
        args.update({k: v for k, v in d.items() if k in ARG_ALANLARI})
    return args


def _ozet(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class Kapi:
    """The gate's state: the tasks of this run (in memory, at most MAX_TASKS), the message ids seen, the rate limit,
    the key. `app` (server.App) gives current_config(), hub, vault_ofis, office.durum_dir, answers and
    answer_decision(); `anahtar_yukle(durum_dir, name)` -> (key, persisted)."""

    def __init__(self, app, anahtar_yukle, log=None, clock=time.monotonic):
        self.app = app
        self.durum_dir = app.office.durum_dir
        self._anahtar_yukle = anahtar_yukle
        self._anahtar = None
        self.sinir = Sinir(clock)
        self.lock = threading.Lock()
        self.kayit_lock = threading.Lock()
        self.tasks = collections.OrderedDict()
        self.mesajlar = collections.OrderedDict()  # messageId -> task id
        self.log = log or (lambda line: None)
        self.is_lock = threading.Lock()  # is-ekle: the hourly check, the delivery and its record in one step
        self.duvar_saati = time.time  # wall clock of the hourly limit (survives restarts; tests replace it)

    # --- configuration and the key ---

    def ayar(self):
        return ayar(self.app.current_config())

    def anahtar(self):
        """The key (created on first use); None when the file could not be written (Jarvis could not read it)."""
        if self._anahtar is None:
            value, kalici = self._anahtar_yukle(self.durum_dir, ANAHTAR_DOSYASI)
            if kalici:
                self._anahtar = value
        return self._anahtar

    def yetkili(self, header):
        key = self.anahtar()
        if not key:
            return False
        scheme, _, verilen = str(header or "").strip().partition(" ")
        if scheme.lower() != "bearer":
            return False
        return hmac.compare_digest(verilen.strip().encode(), key.encode())

    # --- JSON-RPC ---

    def rpc(self, body, surum=None, ayar_=None):
        """The JSON-RPC response object for a parsed request body. `ayar_`: the gate's settings of this request (read
        again when not given)."""
        rid = body.get("id") if isinstance(body, dict) else None
        if isinstance(rid, bool) or not isinstance(rid, (str, int, type(None))):
            rid = None
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
            return cevap(rid, error=hata(INVALID_REQUEST, "Geçersiz JSON-RPC isteği (tek bir istek nesnesi)."))
        if not surum_destekli(surum):
            return cevap(rid, error=hata(VERSION_NOT_SUPPORTED, "Desteklenen A2A sürümleri: 0.3 ve 1.0."))
        method = body["method"]
        params = body.get("params")
        params = {} if params is None else params
        if not isinstance(params, dict):
            return cevap(rid, error=hata(INVALID_PARAMS, "params bir nesne olmalı."))
        if method in UNSUPPORTED:
            return cevap(rid, error=hata(UNSUPPORTED_OP, "Bu kapı akış, bildirim ve görev listesi sunmaz."))
        if method not in METHODS:
            return cevap(rid, error=hata(METHOD_NOT_FOUND, f"Bilinmeyen yöntem: {method[:60]}"))
        kind, dialect = METHODS[method]
        if kind in ("get", "cancel"):
            task = self._task(params.get("id"))
            if task is None:
                return cevap(rid, error=hata(TASK_NOT_FOUND, "Görev bulunamadı."))
            if kind == "cancel":
                return cevap(rid, error=hata(NOT_CANCELABLE, "Bu kapının görevleri iptal edilemez."))
            return cevap(rid, wire(task, dialect))
        task, err = self._send(params, ayar_ or self.ayar() or ayar({KEY: {"acik": True}}))
        if err:
            return cevap(rid, error=err)
        wired = wire(task, dialect)
        return cevap(rid, {"task": wired} if dialect == V1 else wired)

    def _task(self, tid):
        if not isinstance(tid, str):
            return None
        with self.lock:
            task = self.tasks.get(tid)
            return dict(task) if task else None

    def _send(self, params, settings):
        msg = params.get("message")
        if not isinstance(msg, dict) or not isinstance(msg.get("parts"), list) or not msg["parts"]:
            return None, hata(INVALID_PARAMS, "message.parts gerekli.")
        mid = msg.get("messageId")
        if not isinstance(mid, str) or not mid or len(mid) > MAX_ID:
            return None, hata(INVALID_PARAMS, "message.messageId gerekli.")
        if msg.get("role") not in ("user", "ROLE_USER"):
            return None, hata(INVALID_PARAMS, "message.role kullanıcı olmalı.")
        for key in ("taskId", "contextId"):
            if msg.get(key) is not None and (not isinstance(msg[key], str) or not msg[key] or len(msg[key]) > MAX_ID):
                return None, hata(INVALID_PARAMS, f"message.{key} geçersiz.")
        with self.lock:
            seen = self.mesajlar.get(mid)
            if seen and seen in self.tasks:
                return dict(self.tasks[seen]), None  # the same message again: the same task, nothing runs twice
        texts, datas = _parcalar(msg["parts"])
        prev = None
        if msg.get("taskId"):
            prev = self._task(msg["taskId"])
            if prev is None:
                return None, hata(TASK_NOT_FOUND, "Görev bulunamadı.")
            if prev["state"] != "input-required":
                return None, hata(INVALID_PARAMS, "Bu görev bitti; yeni bir mesaj gönder.")
            skill, args = prev["skill"], {**prev["args"], **_args(datas)}
        else:
            skill, args = self._beceri(msg, params, texts, datas)
        izinli = beceriler(settings["kapsam"])
        if skill == "durum":
            state, text, data = self._durum()
        elif skill == "projeler":
            state, text, data = self._projeler()
        elif skill == "kararlar":
            state, text, data = self._kararlar()
        elif skill == "karar-cevapla":
            state, text, data = self._cevapla(args)
        elif skill == IS_EKLE and skill not in izinli:
            state, text, data = "rejected", (
                "Jarvis'ten iş verme bu kapıda kapalı; yeni iş için ofis sayfasını kullan."), {
                "kod": "kapsam-disi", "beceriler": list(izinli)}
        elif skill == IS_EKLE:
            state, text, data = self._is_ekle(args, mid, datas, settings)
        else:
            sohbet = ("CEO ile serbest sohbet yapılamaz; yeni iş isteği is-ekle ile gider."
                      if IS_EKLE in izinli else
                      "İş ekleme, CEO ile sohbet ve başka istekler Jarvis'ten yapılamaz; onlar için ofis sayfasını "
                      "kullan.")
            state, text, data = "rejected", (
                f"Bu kapıdan yalnız şunlar istenebilir: {', '.join(izinli)}. {sohbet}"), {
                "kod": "desteklenmiyor", "beceriler": list(izinli)}
        task = {"id": prev["id"] if prev else str(uuid.uuid4()),
                "contextId": (prev or {}).get("contextId") or msg.get("contextId") or str(uuid.uuid4()),
                "skill": skill if skill in izinli else "",
                "args": args if skill in ("karar-cevapla", IS_EKLE) and skill in izinli else {},
                "state": state, "text": text, "data": data, "timestamp": _now(), "status_mid": str(uuid.uuid4()),
                "artifact_id": str(uuid.uuid4())}
        with self.lock:
            self.tasks[task["id"]] = task
            self.tasks.move_to_end(task["id"])
            while len(self.tasks) > MAX_TASKS:
                self.tasks.popitem(last=False)
            self.mesajlar[mid] = task["id"]
            while len(self.mesajlar) > MAX_TASKS * 2:
                self.mesajlar.popitem(last=False)
        return dict(task), None

    @staticmethod
    def _beceri(msg, params, texts, datas):
        """(skill id or "", args): metadata.skill, else a data part's skill, else a text part that is exactly an id."""
        args = _args(datas)
        for meta in (msg.get("metadata"), params.get("metadata")):
            if isinstance(meta, dict) and isinstance(meta.get("skill"), str):
                return meta["skill"].strip(), args
        for d in datas:
            if isinstance(d.get("skill"), str):
                return d["skill"].strip(), args
        for t in texts:
            if t.strip().lower() in SKILLS:
                return t.strip().lower(), args
        return "", args

    # --- the skills ---

    def _kartlar(self):
        """[(card, mudur_karti)] answerable from the page: pending decisions and the manager cards."""
        vault = self.app.vault_ofis
        return [(c, False) for c in state_mod.pending_decisions(vault)] + \
            [(c, True) for c in mudur.kararlar(vault)]

    def _kararlar_listesi(self):
        sent = self.app.answers.notes()
        return [kart_verisi(c, sent, m) for c, m in self._kartlar()]

    def _durum(self):
        state, _ = self.app.hub.snapshot()
        state = state or {}
        tz = ((state.get("sahne") or {}).get("saat_dilimi")) or model_durum.yerel_saat_dilimi()
        try:
            harcama = muhasebe.ozet(self.app.vault_ofis, state.get("board") or [], tz=tz)["bugun"]
        except Exception:  # noqa: BLE001 — the status still answers without today's job spending
            harcama = {}
        data = durum_verisi(state, harcama, self._kararlar_listesi(), projeler(self.app.current_config()))
        return "completed", durum_metni(data), data

    def _projeler(self):
        items = projeler(self.app.current_config())
        if not items:
            return "completed", "Kayıtlı proje yok.", {"projeler": []}
        lines = [f"{len(items)} proje:"] + [f"- {p['ad']}" + (f" — {p['aciklama']}" if p["aciklama"] else "")
                                             for p in items]
        return "completed", "\n".join(lines), {"projeler": items}

    def _kararlar(self):
        items = self._kararlar_listesi()
        return "completed", kararlar_metni(items), {"kararlar": items}

    def _cevapla(self, args):
        note, metin = args.get("note"), args.get("cevap")
        if not isinstance(note, str) or not note.strip():
            return "rejected", "Hangi karar? note alanı gerekli (kararlar listesindeki not adı).", {"kod": "eksik"}
        note = note.strip()
        if not isinstance(metin, str) or not metin.strip():
            return "input-required", "Cevabın nedir? cevap alanı boş.", {"kod": "cevap-gerekli", "note": note}
        metin = metin.strip()
        if len(metin) > MAX_CEVAP:
            return "rejected", f"Cevap en çok {MAX_CEVAP} karakter olabilir.", {"kod": "uzun", "note": note}
        card = next((c for c, _ in self._kartlar() if c.get("note") == note), None)
        if card is None:
            status = state_mod.decision_status(self.app.vault_ofis, note)
            text = {"invalid": "Geçersiz karar adı.", "missing": "Böyle bir karar yok.",
                    "not_pending": "Bu karar zaten cevaplanmış."}.get(status, "Bu karar şu an cevaplanamıyor.")
            kod = {"invalid": "gecersiz", "missing": "yok", "not_pending": "cevaplanmis"}.get(status, "cevaplanamaz")
            return "rejected", text, {"kod": kod, "note": note}
        final, err = secenek_cevabi(card, metin)
        if err:
            return "rejected", err, {"kod": "secenek-yok", "note": note,
                                     "secenekler": [o.get("kod") for o in card.get("options") or []]}
        ozet = _ozet(final)
        zaten = ("completed", "Bu cevap zaten iletildi; ikinci kez gönderilmedi.",
                 {"note": note, "cevap": final, "zaten_iletildi": True})
        if self._jarvis_gonderdi(note) == ozet and note in self.app.answers.notes():
            return zaten
        risk, neden = risk_sinifla(card)
        if risk == "yuksek" and args.get("ekran_onayi") is not True:
            return "input-required", (
                f"Bu karar yüksek riskli ({neden}). Cevabı ekrandaki onay düğmesiyle ver; sesle onay yetmez."), {
                "kod": "ekran_onayi_gerekir", "note": note, "risk": risk, "risk_nedeni": neden,
                "ekran_onayi_gerekir": True}

        def after():
            self._kaydet(note, ozet)
            self._not_isaretle(note)
            self.log(f"ofis: karar cevabı Jarvis üzerinden iletildi: {note}")
        code, payload = self.app.answer_decision(note, final, after=after)
        if code == 202:
            text = ("CEO şu an meşgul; cevabın sıraya alındı, ilk fırsatta iletilecek."
                    if payload.get("status") == "queued" else "Cevabın CEO'ya iletildi.")
            return "completed", text, {"note": note, "cevap": final, "iletim": payload.get("status"),
                                                    "zaten_iletildi": False, "kanal": KANAL}
        if code == 409 and payload.get("kod"):
            if self._jarvis_gonderdi(note) == ozet:
                return zaten
            return "rejected", payload.get("error", ""), {"kod": payload["kod"], "note": note}
        if code == 409:
            return "failed", "CEO'ya şu an ulaşılamıyor; biraz sonra yeniden dene.", {"kod": "ceo-ulasilamiyor",
                                                                                      "note": note}
        return "rejected", "Bu karar şu an cevaplanamıyor.", {"kod": "cevaplanamaz", "note": note}

    def _is_ekle(self, args, mid, datas, settings):
        """The owner's spoken request -> one top-level `[Sahip · Jarvis]` prompt to the CEO via the page chat's path."""
        if sum(1 for d in datas if "metin" in d) > 1:
            return "rejected", "Tek seferde tek mesaj gönderilebilir.", {"kod": "tek-mesaj"}
        metin, proje = args.get("metin"), args.get("proje", "")
        if metin is not None and not isinstance(metin, str):
            return "rejected", "metin bir yazı olmalı.", {"kod": "gecersiz"}
        metin = (metin or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not metin:
            return "input-required", "Ne yapılsın? metin alanı boş.", {"kod": "metin-gerekli"}
        if len(metin) > MAX_METIN:
            return "rejected", f"Mesaj en çok {MAX_METIN} karakter olabilir.", {"kod": "uzun"}
        if proje is None:
            proje = ""
        if not isinstance(proje, str):
            return "rejected", "proje bir yazı olmalı.", {"kod": "gecersiz"}
        proje = proje.strip()
        bilinen = [p["ad"] for p in projeler(self.app.current_config())]
        if proje and (not launch.PROJECT_NAME.fullmatch(proje) or proje not in bilinen):
            return "rejected", f"Böyle bir proje yok: {proje[:40]}. Projeler: {', '.join(bilinen)}.", {
                "kod": "proje-yok", "projeler": bilinen}
        if args.get("dugme_onayi") is not True:
            return "input-required", (
                "Mesajı ekrandaki Gönder düğmesiyle onayla; sesle gönderilmez."), {
                "kod": "dugme_onayi_gerekir", "proje": proje, "dugme_onayi_gerekir": True}
        anahtar = _ozet(mid)
        with self.is_lock:
            kayit = self._is_kayitlari()
            onceki = next((r for r in kayit if r.get("mid") == anahtar), None)
            if onceki:
                return "completed", "Bu mesaj zaten iletildi; ikinci kez gönderilmedi.", {
                    "iletildi": True, "mesaj_kimligi": onceki.get("kimlik", ""), "zaten_iletildi": True,
                    "proje": proje, "kanal": KANAL}
            simdi = self.duvar_saati()
            son_saat = [r for r in kayit if isinstance(r.get("zaman"), (int, float)) and simdi - r["zaman"] < 3600]
            sinir = settings["is_saatlik_sinir"]
            if len(son_saat) >= sinir:
                return "rejected", (
                    f"Bir saatte en çok {sinir} iş isteği gönderilebilir; biraz sonra yeniden dene ya da ofis "
                    "sayfasını kullan."), {"kod": "saatlik-sinir", "sinir": sinir}
            govde = (f"Proje: {proje}\n" if proje else "") + metin
            try:
                iletim = self.app.sohbet_ilet(govde, transcript.JARVIS_PREFIX)
            except ceo_mod.CeoUnavailable:
                return "failed", "CEO'ya şu an ulaşılamıyor; biraz sonra yeniden dene.", {"kod": "ceo-ulasilamiyor"}
            kimlik = "jarvis-" + uuid.uuid4().hex[:12]
            self._is_kaydet(kayit, {"mid": anahtar, "kimlik": kimlik, "zaman": simdi})
        self.log(f"ofis: iş isteği Jarvis üzerinden CEO'ya iletildi: {kimlik}" + (f" ({proje})" if proje else ""))
        text = ("CEO şu an meşgul; mesajın sıraya alındı, ilk fırsatta iletilecek." if iletim == "queued"
                else "Mesajın CEO'ya iletildi.")
        return "completed", text, {"iletildi": True, "mesaj_kimligi": kimlik, "iletim": iletim,
                                   "zaten_iletildi": False, "proje": proje, "kanal": KANAL}

    def _is_kayit_yolu(self):
        return os.path.join(self.durum_dir, IS_KAYIT)

    def _is_kayitlari(self):
        try:
            with open(self._is_kayit_yolu(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        rows = data.get("gonderilen") if isinstance(data, dict) else None
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

    def _is_kaydet(self, kayit, row):
        rows = (kayit + [row])[-MAX_KAYIT:]
        path = self._is_kayit_yolu()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"gonderilen": rows}, f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:  # delivered already; only the idempotency / hourly record is missing
            self.log(f"ofis: Jarvis iş isteği kaydı yazılamadı: {type(e).__name__}")

    # --- the Jarvis record and the note mark ---

    def _kayit_yolu(self):
        return os.path.join(self.durum_dir, KAYIT)

    def _kayitlar(self):
        try:
            with open(self._kayit_yolu(), encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _jarvis_gonderdi(self, note):
        rec = self._kayitlar().get(note)
        return rec.get("ozet") if isinstance(rec, dict) else None

    def _kaydet(self, note, ozet):
        with self.kayit_lock:
            data = self._kayitlar()
            data.pop(note, None)
            data[note] = {"ozet": ozet, "zaman": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
            while len(data) > MAX_KAYIT:
                data.pop(next(iter(data)))
            path = self._kayit_yolu()
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = f"{path}.{os.getpid()}.tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(tmp, path)
            except OSError as e:  # the answer is delivered already; only the idempotency record is missing
                self.log(f"ofis: Jarvis cevap kaydı yazılamadı: {type(e).__name__}")

    def _not_isaretle(self, note):
        """`cevap_kanali: Jarvis üzerinden` in the decision note (under the job lock, like every note writer)."""
        vault = self.app.vault_ofis
        try:
            with jobs.locked(vault):
                path = mudur._note_path(vault, note)
                if path is None:
                    return
                lines, _, body = mudur._read_note(path)
                jobs._set_line(lines, KANAL_ALANI, KANAL)
                jobs._write_atomic(path, jobs.render(lines, body))
        except (OSError, UnicodeDecodeError, jobs.JobError) as e:
            self.log(f"ofis: Jarvis kanalı karar notuna yazılamadı: {note}: {type(e).__name__}")
