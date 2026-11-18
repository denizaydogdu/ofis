"""The morning summary (plan "Sonraki iş (7)" Ekler, owner decision 2026-11-12): every morning at ofis.json `sabah_ozeti`
(default "08:30", the office time zone ofis_sahnesi.saat_dilimi) the server writes OFIS/Ozetler/YYYY-MM-DD.md and sends
the CEO ONE "[Ofis · sistem]" notice "Sabah özeti hazır: [[YYYY-MM-DD]] …" with 3–5 key lines. Deterministic, no model
call. Contents: yesterday's finished jobs with their Kontrol proof and $ · tokens, the pending decisions, the stuck or
stopped jobs, today's queue and schedules, one line per project, yesterday's total spending of the jobs, the Sunucu
odası's open suggestions and domain problems, the questions the managers answered yesterday and, separately, the ones
a manager handed back to the owner yesterday with the short reason (bin/mudur.py: two sections, and " · dün müdür kararı:
N" / " · müdürün <sahip>'e bıraktığı: K" on the notice's decision line when there were any).
When the latest memory health report (bin/hafiza_saglik.py, today's or yesterday's) found problems, one line under the
short table names it ("Hafıza sağlığı: N sorun · [[Saglik-YYYY-MM-DD]]").
It also names yesterday's end-of-day review (bin/gunsonu.py dunku): the note's link [[GunSonu-YYYY-MM-DD]] with the
number of bad cases and the review job, or that the evening window was skipped.

Catch-up: only the latest slot counts (today's once its time has come, else yesterday's), so a summary missed while the
server was off is written once and only within 24 hours; an older one never. Never two for one day: the state file
durum/ozet/son.json (the days written) and the note itself are both checked. A note that cannot be written sends no
notice (tried again on the next pass)."""
import json
import os
import re
import threading
from datetime import datetime, timedelta

import budget
import jobs
import model_durum
import mudur
import sahip
import sorumlu

FOLDER = "Ozetler"
DEFAULT_SAAT = (8, 30)
SAAT = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
STATE_DIR = "ozet"
STATE_FILE = "son.json"
KEEP_DAYS = 30
SYSTEM_PREFIX = "[Ofis · sistem]\n"
AYLAR = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık")
ACIK = ("baslatiliyor", "calisiyor", "kontrolde", "karar-bekliyor", "incelemede")
KONTROL = {"gecti": "Kontrol geçti", "kaldi": "Kontrol geçmedi", "yok": "kontrol yok",
           "kayit-yok": "güvenilir kontrol kaydı yok", "calistirilmadi": "Kontrol çalıştırılmadı"}
MAX_LIST = 25


def saat(cfg):
    """(hour, minute) of ofis.json `sabah_ozeti` ("HH:MM"), else DEFAULT_SAAT."""
    value = (cfg or {}).get("sabah_ozeti")
    m = SAAT.fullmatch(value) if isinstance(value, str) else None
    return (int(m.group(1)), int(m.group(2))) if m else DEFAULT_SAAT


def son_slot(hm, now):
    """The latest summary time at or before `now` (an aware datetime in the office zone)."""
    slot = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    return slot if now >= slot else slot - timedelta(days=1)


def _tz(cfg):
    """The office zone (ofis.json ofis_sahnesi.saat_dilimi, else the system's local zone: bin/model_durum.py)."""
    return model_durum.office_tz(model_durum.saat_dilimi(cfg))


def tarih_metni(gun):
    d = datetime.strptime(gun, "%Y-%m-%d")
    return f"{d.day} {AYLAR[d.month - 1]} {d.year}"


def _veri(text, limit=sorumlu.SATIR_SINIRI):
    """Model- or project-derived text (titles, the manager's short reason, suggestions, names) as one inert line of the
    note: sorumlu.tek_satir (control characters and newlines collapsed, cut to `limit`, "[" "]" "|" escaped, "](" broken —
    so no "[[x]]", "![](…)" or "[a](…)" link or embed survives) and, on top, "<" / ">" as HTML entities (no <img> or other
    tag that could load remote content in Obsidian) and no backticks (no code span breaking out)."""
    text = sorumlu.tek_satir(str(text or "").replace("`", "'"), limit)
    return text.replace("](", "] (").replace("<", "&lt;").replace(">", "&gt;")


def _link(note):
    stem = str(note or "")
    stem = stem[:-3] if stem.endswith(".md") else stem
    ok = jobs.NOTE_NAME.fullmatch(stem + ".md") and not re.search(r"[\[\]|#^]", stem)
    return f"[[{stem}]]" if ok else _veri(stem)


def _spend(t):
    try:
        usd = float(t.get("spent"))
    except (TypeError, ValueError):
        return ""
    return budget.spend_text(usd, t.get("tokens"))


def _kontrol(t):
    if not t.get("_kayit"):  # no server record: the note alone is never proof
        return "kontrol bilinmiyor"
    text = KONTROL.get(str(t.get("kontrol_sonuc") or ""), "kontrol yok")
    n = t.get("kontrol_deneme")
    if t.get("kontrol_sonuc") == "gecti" and isinstance(n, int) and n > 0:
        text += f" ({n}. deneme)"
    return text


def _is(t, *extra):
    bits = [f"{_link(t.get('note'))} — {_veri(t.get('title') or '', 100)}",
            *[e for e in extra if e]]
    return " · ".join(bits)


def _liste(items, bos):
    if not items:
        return bos
    more = len(items) - MAX_LIST
    return "\n".join(f"- {x}" for x in items[:MAX_LIST]) + (f"\n- … ve {more} tane daha" if more > 0 else "")


def _kisaca(v):
    """The short summary table at the top of the note (the owner, 2026-11-13: the numbers first, then the sections)."""
    gecen = sum(1 for t in v["biten"] if t.get("_kayit") and t.get("kontrol_sonuc") == "gecti")
    h = v["harcama"]
    rows = [("Dün biten", f"{len(v['biten'])} iş"), ("Kontrol geçen", str(gecen)),
            ("Dünkü kullanım", f"{budget.spend_text(h.get('usd') or 0.0, h.get('token'))} · "
                              f"{int(h.get('is_sayisi') or 0)} iş" if h else "kayıt yok"),
            ("Bekleyen karar", str(len(v["kararlar"]))), ("Takılan", str(len(v["takilan"]))),
            ("Bugün sırada", f"{len(v['sirada'])} iş, {len(v['zamanlanmis'])} zamanlanmış iş"),
            ("Sunucu odası", f"{len(v['oneriler'])} öneri, {len(v['domain'])} domain sorunu")]
    return "## Kısaca\n\n| Konu | Durum |\n|---|---|\n" + "\n".join(
        f"| {k} | {val.replace('|', '/')} |" for k, val in rows) + "\n"


def metin(gun, v):
    """The note's text for day `gun` from the gathered data `v` (SabahOzeti.veri)."""
    out = [f"---\ntur: sabah-ozeti\ntarih: {gun}\ndurum: yazildi\n---\n",
           f"# Sabah özeti — {tarih_metni(gun)}\n",
           "> Bu notu ofis sunucusu yazar (model çağrısı yok); elle düzenlenmez.\n"]
    out.append(_kisaca(v))
    s = v.get("saglik")
    if isinstance(s, dict) and isinstance(s.get("sorun"), int) and s["sorun"] > 0:  # bin/hafiza_saglik.py
        out.append(f"Hafıza sağlığı: {s['sorun']} sorun · {_link(s.get('not'))}\n")
    if v.get("limitler"):  # bin/limitler.py satir: the owner's Claude plan usage limits
        out.append(_veri(v["limitler"], 300) + "\n")
    out.append("## Dün biten işler\n\n" + _liste(
        [_is(t, t.get("status"), _kontrol(t), _spend(t)) for t in v["biten"]], "Dün biten iş yok.") + "\n")
    out.append("## Dünkü gün sonu değerlendirmesi\n\n" + _gun_sonu_satiri(v.get("gun_sonu")) + "\n")
    out.append("## Bekleyen kararlar\n\n" + _liste(
        [f"{_link(d.get('note'))} — {_veri(d.get('title') or '', 100)}"
         + (f" · {_veri(d.get('project'), 30)}" if d.get("project") else "") for d in v["kararlar"]],
        "Bekleyen karar yok.") + "\n")
    out.append("## Dün müdürlerin cevapladığı sorular\n\n" + _liste(
        [f"{_link(m.get('note'))} — {_veri(m.get('unvan') or '', 40)}"
         + (f" · {_veri(m.get('proje'), 30)}" if m.get("proje") else "")
         + (f" · {sahip.ad()} kendi cevabıyla değiştirdi" if m.get("degisti") else "") for m in v.get("mudur") or []],
        "Dün müdür kararı yok.") + "\n")
    out.append(f"## Dün müdürlerin {sahip.e()} bıraktığı sorular\n\n" + _liste(
        [f"{_link(m.get('note'))} — {_veri(m.get('neden') or m.get('unvan') or '', 220)}"
         + (f" · {_veri(m.get('proje'), 30)}" if m.get("proje") else "")
         + (f" · hâlâ {sahip.in_()} cevabını bekliyor" if m.get("acik") else "") for m in v.get("mudur_deniz") or []],
        f"Dün müdürün {sahip.e()} bıraktığı soru yok.") + "\n")
    out.append("## Takılan ya da durdurulan işler\n\n" + _liste(
        [_is(t, t.get("status"), str(t.get("finished") or "")[:16].replace("T", " ")) for t in v["takilan"]],
        "Takılan iş yok.") + "\n")
    sira = [_is(t, _veri(t.get("project"), 30), "bekletiliyor" if t.get("held") else "",
                "engel var" if t.get("blocked") else "") for t in v["sirada"]]
    zam = [f"Zamanlanmış: {_veri(z.get('ad'), 40)} · {_veri(z.get('proje'), 30)} · "
           f"{_veri(z.get('sonraki'), 20)}" for z in v["zamanlanmis"]]
    out.append("## Bugün sırada\n\n" + _liste(sira + zam, "Sırada iş ve bugün zamanlanmış iş yok.") + "\n")
    out.append("## Projeler\n\n" + _liste([f"{p}: {line}" for p, line in v["projeler"]], "Kayıtlı proje yok.") + "\n")
    h = v["harcama"]
    out.append("## Dünkü toplam kullanım\n\n" + (
        f"{budget.spend_text(h.get('usd') or 0.0, h.get('token'))} · {int(h.get('is_sayisi') or 0)} iş "
        "(dolar işlerin API fiyatıyla karşılığıdır, abonelikte para ödenmez; CEO hariç)" if h else "Kayıtlı kullanım yok.") + "\n")
    sunucu = [f"Öneri: {_veri(o, 200)}" for o in v["oneriler"]] + \
        [f"Domain: {_veri(d, 200)}" for d in v["domain"]]
    out.append("## Sunucu odası\n\n" + _liste(sunucu, "Açık öneri ve domain sorunu yok.") + "\n")
    return "\n".join(out)


def _gun_sonu_satiri(g):
    """Yesterday's end-of-day review (bin/gunsonu.py dunku): its note's link, or that it was skipped."""
    if not isinstance(g, dict):
        return "Dün gün sonu değerlendirmesi yapılmadı (kapalı ya da kaydı yok)."
    if g.get("atlandi"):
        return "Dünkü gün sonu değerlendirmesi atlandı (akşam penceresinde bilgisayar ya da sunucu kapalıydı)."
    line = f"{_link(g.get('not'))} — kötü giden {int(g.get('kotu') or 0)} durum"
    return line + (f" · değerlendirme işi {_link(g.get('is'))}" if g.get("is") else "")


def _mudur_ozeti(items, deniz=()):
    """" · dün müdür kararı: N (<sahip>'in değiştirdiği M) · müdürün <sahip>'e bıraktığı: K" for the notice's decision
    line; each part only when there were any (step 4)."""
    out = ""
    if items:
        changed = sum(1 for m in items if m.get("degisti"))
        out += f" · dün müdür kararı: {len(items)}" + (f" ({sahip.in_()} değiştirdiği {changed})" if changed else "")
    if deniz:
        out += f" · müdürün {sahip.e()} bıraktığı: {len(deniz)}"
    return out


def _baslamayan(takilan):
    """" (başlatılamayan N: …)" for the jobs that never started (basarisiz), titles first: the office's own jobs
    (gün sonu, Ar-Ge) failing to start must not hide in one count (owner decision 2026-11-15)."""
    items = [t for t in takilan if t.get("status") == "basarisiz"]
    if not items:
        return ""
    names = ", ".join(str(t.get("title") or t.get("note") or "")[:60] for t in items[:3])
    return f" (başlatılamayan {len(items)}: {names}" + (" …" if len(items) > 3 else "") + ")"


def bildirim(gun, v):
    """The CEO notice: the title line and 3–5 key lines."""
    gecen = sum(1 for t in v["biten"] if t.get("_kayit") and t.get("kontrol_sonuc") == "gecti")
    h = v["harcama"]
    lines = [f"- Dün biten: {len(v['biten'])} iş (Kontrol geçen {gecen})"
             + (f" · dünkü kullanım {budget.spend_text(h.get('usd') or 0.0, h.get('token'))}" if h else ""),
             f"- Bekleyen karar: {len(v['kararlar'])}" + _mudur_ozeti(v.get("mudur") or [], v.get("mudur_deniz") or []),
             f"- Takılan ya da durdurulan: {len(v['takilan'])}" + _baslamayan(v["takilan"]),
             f"- Bugün sırada: {len(v['sirada'])} iş, {len(v['zamanlanmis'])} zamanlanmış iş"]
    if v["oneriler"] or v["domain"]:
        lines.append(f"- Sunucu odası: {len(v['oneriler'])} öneri, {len(v['domain'])} domain sorunu")
    if v.get("limitler"):
        lines.append(f"- {v['limitler']}")
    return (f"{SYSTEM_PREFIX}Sabah özeti hazır: [[{gun}]] — {tarih_metni(gun)} özeti Obsidian'da.\n"
            + "\n".join(lines))


class SabahOzeti:
    """The server's pass: kontrol() writes the latest due summary once (see the module doc)."""

    def __init__(self, cfg, durum_dir, ceo, now=None, oneriler=None, log=None):
        self.cfg = cfg  # a callable: ofis.json as it is now
        self.durum_dir = durum_dir
        self.ceo = ceo
        self.now = now
        self.oneriler = oneriler or (lambda: [])  # the Sunucu odası's open suggestions (texts)
        self.log = log or (lambda line: None)
        self._lock = threading.Lock()

    def _state_path(self):
        return os.path.join(self.durum_dir, STATE_DIR, STATE_FILE)

    def _done(self):
        try:
            with open(self._state_path(), encoding="utf-8") as f:
                data = json.load(f)
            days = data.get("gunler") if isinstance(data, dict) else None
            return [d for d in days if isinstance(d, str)] if isinstance(days, list) else []
        except (OSError, ValueError):
            return []

    def _mark(self, gun):
        days = sorted(set(self._done()) | {gun})[-KEEP_DAYS:]
        os.makedirs(os.path.dirname(self._state_path()), exist_ok=True)
        jobs._write_atomic(self._state_path(), json.dumps({"gunler": days}, ensure_ascii=False, indent=1) + "\n")

    def veri(self, cfg, gun):
        import sistem  # lazy: the state modules are heavy
        import state
        import zamanla
        import muhasebe
        vault = os.path.expanduser(cfg["vault_ofis"])
        dun = (datetime.strptime(gun, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        tasks = state.recent_tasks(vault, limit=0, cfg=cfg, durum_dir=self.durum_dir)
        for t in tasks:  # the Kontrol proof comes from the server record (a session can edit its note), like karne
            rec = state.cached_record(self.durum_dir, t.get("note")) if self.durum_dir else None
            t["_kayit"] = isinstance(rec, dict)
            if t["_kayit"]:
                t["kontrol_sonuc"] = str(rec.get("kontrol_sonuc") or "")
                n = rec.get("kontrol_deneme")
                t["kontrol_deneme"] = n if isinstance(n, int) else 0
        by_note = lambda t: str(t.get("note"))  # noqa: E731
        biten = sorted((t for t in tasks if t.get("status") in jobs.FINAL_STATUSES and t.get("status") not in ("tikandi", "basarisiz")
                        and str(t.get("finished") or "")[:10] == dun), key=by_note)
        takilan = sorted((t for t in tasks if t.get("status") in ("tikandi", "basarisiz")
                          and dun <= str(t.get("finished") or "")[:10] <= gun), key=by_note)
        # a stuck job finished yesterday also counts as yesterday's finished job (its proof says it did not pass)
        biten = sorted(biten + [t for t in takilan if str(t.get("finished") or "")[:10] == dun], key=by_note)
        sirada = sorted((t for t in tasks if t.get("status") == "sirada"), key=by_note)
        tz = _tz(cfg)
        sonu = datetime.strptime(dun, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=tz)
        try:
            harcama = muhasebe.ozet(vault, tasks, now=sonu, tz=str(tz.key))["bugun"]
        except Exception:  # noqa: BLE001 — the spending line only
            harcama = {}
        zamanli = []
        try:
            for z in zamanla.summaries(self.durum_dir, datetime.strptime(gun, "%Y-%m-%d")):
                if not z.get("duraklatildi") and str(z.get("sonraki") or "").startswith(gun):
                    zamanli.append(z)
        except Exception:  # noqa: BLE001
            zamanli = []
        projeler = []
        for p in sorted((cfg.get("projects") or {})):
            mine = [t for t in tasks if t.get("project") == p]
            calisan = sum(1 for t in mine if t.get("status") in ACIK)
            sira = sum(1 for t in mine if t.get("status") == "sirada")
            dun_biten = sum(1 for t in biten if t.get("project") == p)
            projeler.append((p, f"{calisan} çalışan · {sira} sırada · dün {dun_biten} bitti"))
        try:
            oneriler = [o for o in self.oneriler() if isinstance(o, str)]
        except Exception:  # noqa: BLE001 — the computer could not be read: no suggestions this morning
            oneriler = []
        domain = []
        try:
            d = sistem.domain_ozeti(self.durum_dir, cfg)
            for row in d.get("domainler") or []:
                for s in row.get("sorunlar") or []:
                    domain.append(f"{row.get('proje')}: {row.get('domain')} — {s.get('metin')}")
        except Exception:  # noqa: BLE001
            domain = []
        try:  # step 4: the questions the managers answered yesterday (bin/mudur.py)
            mudur_kararlari = mudur.dunku(self.durum_dir, vault, dun)
        except Exception:  # noqa: BLE001 — that section only
            mudur_kararlari = []
        try:  # the questions a manager handed back to the owner yesterday, with the short reason
            mudur_deniz = mudur.dunku_deniz(self.durum_dir, vault, dun)
        except Exception:  # noqa: BLE001 — that section only
            mudur_deniz = []
        try:  # yesterday's end-of-day review note (bin/gunsonu.py; lazy: it imports this module)
            import gunsonu
            gun_sonu = gunsonu.dunku(self.durum_dir, dun)
        except Exception:  # noqa: BLE001 — that line only
            gun_sonu = None
        try:  # the latest memory health report (bin/hafiza_saglik.py; lazy: it imports this module)
            import hafiza_saglik
            saglik = hafiza_saglik.ozet_icin(self.durum_dir, gun)
        except Exception:  # noqa: BLE001 — that line only
            saglik = None
        try:  # The owner's Claude plan usage limits (bin/limitler.py; None when off or without data)
            import limitler
            limit_satiri = limitler.satir(cfg)
        except Exception:  # noqa: BLE001 — that line only
            limit_satiri = None
        return {"biten": biten, "kararlar": state.pending_decisions(vault), "mudur": mudur_kararlari,
                "gun_sonu": gun_sonu, "saglik": saglik, "limitler": limit_satiri,
                "mudur_deniz": mudur_deniz,
                "takilan": takilan, "sirada": sirada,
                "zamanlanmis": zamanli, "projeler": projeler, "harcama": harcama, "oneriler": oneriler,
                "domain": domain}

    def kontrol(self):
        """Writes the latest due summary when it is not written yet; returns its day, else None."""
        with self._lock:
            cfg = self.cfg()
            tz = _tz(cfg)
            now = self.now() if self.now else datetime.now(tz)
            now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
            slot = son_slot(saat(cfg), now)
            if now - slot >= timedelta(hours=24):
                return None
            gun = slot.strftime("%Y-%m-%d")
            vault = os.path.expanduser(str(cfg.get("vault_ofis") or ""))
            folder = os.path.join(vault, FOLDER)
            target = os.path.join(folder, f"{gun}.md")
            if gun in self._done():
                return None
            if os.path.lexists(target):  # written, but the notice / mark did not follow (enqueue is idempotent by key)
                self.ceo.enqueue(bildirim(gun, self.veri(cfg, gun)), f"sabah-ozeti-{gun}")
                self._mark(gun)
                return None
            v = self.veri(cfg, gun)
            text = metin(gun, v)
            try:
                if os.path.islink(folder):
                    raise OSError("the Ozetler folder is a link")
                os.makedirs(folder, exist_ok=True)
                jobs._write_atomic(target, text)
            except OSError as e:
                self.log(f"ofis: sabah özeti yazılamadı: {type(e).__name__}")
                return None
            self.ceo.enqueue(bildirim(gun, v), f"sabah-ozeti-{gun}")
            self._mark(gun)
            return gun

    def run(self, stop_event, interval=30):
        while not stop_event.is_set():
            try:
                self.kontrol()
            except Exception as e:  # noqa: BLE001 — never stops the server
                self.log(f"ofis: sabah özeti hatası: {type(e).__name__}: {e}")
            stop_event.wait(interval)
