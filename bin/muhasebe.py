"""The Muhasebe (accounting) numbers for the page's Muhasebeci card: GET /api/muhasebe.

Read-only. Finished jobs come from the Karne rows (OFIS/Karne/Kayitlar-YYYY-MM.md, read with karne's own parser; a
row is written once a job is final), the jobs still open from the page state's board (every non-final job, with its
recorded spending `harcanan_usd` / `harcanan_token`). A job is counted once: an open job that already has a Karne row
(a job that went on with `devam` keeps its row) is taken from the row. Day and month are read in the office time
zone (ofis.json ofis_sahnesi.saat_dilimi). Unknown tokens stay None (shown as "—"), never 0. Codex and the free
reviewers are not priced: `codex_fiyatsiz` counts the Codex review rows/jobs of the period so the card can say so.

The Karne rows are parsed again only when a Kayitlar file changes (cache keyed by their mtimes and sizes).

The NPC chat usage (bin/npc_sohbet.py's records, `durum_dir`) joins the day and month totals: its dollars and known
tokens are part of the office's usage, its questions never count as jobs — is_sayisi, the per-project / per-role
breakdowns, the budget view and every quality number stay job-only; each period carries its own `npc_sohbet` total
({usd, token, soru}; zero questions = nothing added).
"""
import os
import re
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import karne
import model_durum

OPEN = ("baslatiliyor", "calisiyor", "kontrolde", "karar-bekliyor", "incelemede")
ROLE_ORDER = ("Stajyer", "Uzman", "Kıdemli", "Genel Müdür", "Dış denetçi")
NEAR = 0.8  # a job at 80 % of its budget is "near" it
LINK = re.compile(r"\[\[(.+)\]\]")

_lock = threading.Lock()
_cache = {"key": None, "rows": [], "events": {}}


def _rows(vault):
    """karne's rows (and rework events), parsed again only when a Kayitlar/Duzeltmeler file changed."""
    folder = os.path.join(vault, karne.FOLDER)
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        names = []
    key = []
    for n in names:
        if karne.RECORDS.fullmatch(n) or n.startswith("Duzeltmeler-"):
            try:
                st = os.stat(os.path.join(folder, n))
            except OSError:
                continue
            key.append((n, st.st_mtime_ns, st.st_size))
    key = tuple(key)
    with _lock:
        if _cache["key"] != key:
            _cache.update(key=key, rows=karne._rows(vault), events=karne._rework_events(vault))
        return _cache["rows"], _cache["events"]


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value):
    s = str(value if value is not None else "").strip()
    return int(s) if s.isascii() and s.isdigit() else None


def _role(model):
    return karne.ROLES.get(_family(model), "")


def _family(model):
    low = str(model or "").lower()
    return next((f for f in karne.ROLES if f in low), "")


def _stem(row):
    m = LINK.fullmatch(row.get("İş", ""))
    return m.group(1) if m else ""


def _totals(items):
    """{usd, token (None when none known), token_bilinen, is_sayisi, proje: {...}, rol: {...}, codex_fiyatsiz}."""
    def add(bucket, item):
        bucket["usd"] = round(bucket["usd"] + (item["usd"] or 0.0), 6)
        bucket["is_sayisi"] += 1
        if item["token"] is not None:
            bucket["token"] = (bucket["token"] or 0) + item["token"]
            bucket["token_bilinen"] += 1
    def empty():
        return {"usd": 0.0, "token": None, "token_bilinen": 0, "is_sayisi": 0}
    total, projects, roles = empty(), {}, {}
    codex = 0
    for it in items:
        add(total, it)
        add(projects.setdefault(it["proje"] or "—", empty()), it)
        if it["rol"]:
            add(roles.setdefault(it["rol"], empty()), it)
        codex += it["codex"]
    order = {r: i for i, r in enumerate(ROLE_ORDER)}
    return {**total, "codex_fiyatsiz": codex,
            "proje": [{"proje": p, **v} for p, v in sorted(projects.items(), key=lambda x: (-x[1]["usd"], x[0]))],
            "rol": [{"rol": r, **v} for r, v in sorted(roles.items(), key=lambda x: (order.get(x[0], 99), x[0]))]}


def _uzmanliklar(items):
    groups = {}
    for i in items:
        g = groups.setdefault(i.get("uzmanlik") or "", {"is_sayisi": 0, "usd": 0.0})
        g["is_sayisi"] += 1
        g["usd"] = round(g["usd"] + (i["usd"] or 0.0), 6)
    order = {u: n for n, u in enumerate(karne.UZMANLIK_SIRA)}
    return [{"uzmanlik": u, **v} for u, v in sorted(groups.items(), key=lambda x: (x[0] == "", order.get(x[0], 99),
                                                                                    x[0]))]


def _npc_gunler(record, zone):
    """(day, month) of one NPC chat record in the office zone, ("", "") for a stamp that cannot be read."""
    try:
        t = datetime.fromtimestamp(record["zaman"], zone)
    except (KeyError, OSError, OverflowError, TypeError, ValueError):
        return "", ""
    return t.strftime("%Y-%m-%d"), t.strftime("%Y-%m")


def _npc_ekle(totals, npc):
    """One period's totals with the NPC chat usage (see the module doc): the dollars and the known tokens join the
    total, the questions stay their own count — is_sayisi and the breakdowns are jobs only."""
    out = dict(totals)
    out["npc_sohbet"] = {"usd": npc["usd"], "token": npc["token"], "soru": npc["soru"]}
    if npc["soru"]:
        out["usd"] = round(totals["usd"] + npc["usd"], 6)
        if totals["token"] is not None or npc["token"] is not None:
            out["token"] = (totals["token"] or 0) + (npc["token"] or 0)
        out["token_bilinen"] = totals["token_bilinen"] + npc["token_bilinen"]
    return out


def ozet(vault, board, now=None, tz=None, durum_dir=None):
    """The accounting summary for the page (see the module doc). `board` = the state's board jobs (or tasks); `tz` =
    the office zone's name (default: the system's local zone); `durum_dir` = the server's state folder, for the NPC
    chat usage that joins the day and month totals."""
    import npc_sohbet  # lazy: it imports launch and the state modules' friends
    tz = tz or model_durum.yerel_saat_dilimi()
    zone = ZoneInfo(tz)
    now = now or datetime.now(zone)
    local = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)
    today, month = local.strftime("%Y-%m-%d"), local.strftime("%Y-%m")
    rows, events = _rows(vault)
    titles = {str(t.get("note", ""))[:-3]: t for t in board or [] if isinstance(t, dict)}
    seen, items = {}, []
    for r in rows:
        stem = _stem(r)
        t = titles.get(stem, {})
        items.append({"not": f"{stem}.md" if stem else "", "baslik": t.get("title") or stem, "proje": r["Proje"],
                      "tarih": r["Tarih"], "usd": _float(r["Maliyet ($)"]), "token": _int(r.get("Token")),
                      "rol": _role(r["Model"]), "codex": 1 if r["Model"] == "codex" else 0, "acik": False, "row": r,
                      "uzmanlik": r.get("Uzmanlık", "")})
        if stem:
            seen[stem] = items[-1]
    running = []
    for t in board or []:
        if not isinstance(t, dict) or t.get("status") not in OPEN:
            continue
        stem = str(t.get("note", ""))[:-3]
        if not stem:
            continue
        usd = _float(t.get("spent"))
        old = seen.get(stem)
        if old is not None:
            # running again after devam: counted once — its Karne row, with the live spending when that is higher
            if usd is not None and (old["usd"] is None or usd > old["usd"]):
                old["usd"], old["acik"] = usd, True
                tok = _int(t.get("tokens"))
                if tok is not None:
                    old["token"] = tok
            item = old
        else:
            # an open job is dated by its start (like a row by its finish), never simply "today"
            day = str(t.get("started") or t.get("created") or "")[:10]
            item = {"not": t.get("note", ""), "baslik": t.get("title") or stem, "proje": t.get("project", ""),
                    "tarih": day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else today, "usd": usd,
                    "token": _int(t.get("tokens")), "rol": _role(t.get("model")),
                    "codex": 1 if str(t.get("inceleme_yurutucu", "")).startswith("codex") else 0, "acik": True,
                    "uzmanlik": str(t.get("uzmanlik") or "")}
            items.append(item)
            seen[stem] = item
        budget = _float(t.get("budget"))
        usd = item["usd"]
        running.append({"not": item["not"], "baslik": item["baslik"], "proje": item["proje"], "usd": usd,
                        "token": item["token"], "butce": budget})
    day = [i for i in items if i["tarih"] == today]
    mon = [i for i in items if i["tarih"].startswith(month)]
    # the NPC chat usage of the two periods (a question is never a job: only the dollars and tokens join)
    kayit = [(*_npc_gunler(r, zone), r) for r in (npc_sohbet.kullanimlar(durum_dir) if durum_dir else [])]
    npc_gun = npc_sohbet.kullanim_toplami([r for gun, _, r in kayit if gun == today])
    npc_mon = npc_sohbet.kullanim_toplami([r for _, ay, r in kayit if ay == month])
    measured = karne._rounded(karne._measure([i["row"] for i in mon if "row" in i], events))
    top = sorted((i for i in mon if i["usd"]), key=lambda i: (-i["usd"], i["not"]))[:3]
    spent = sum(r["usd"] or 0.0 for r in running)
    known = [r["token"] for r in running if r["token"] is not None]  # unknown tokens are never counted as 0
    budgets = [r for r in running if r["butce"]]
    flagged = [{**r, "durum": "asti" if (r["usd"] or 0) > r["butce"] else "yakin"} for r in budgets
               if (r["usd"] or 0) >= NEAR * r["butce"]]
    return {
        "gun": today, "ay": month, "saat_dilimi": tz,
        "bugun": _npc_ekle(_totals(day), npc_gun), "bu_ay": _npc_ekle(_totals(mon), npc_mon),
        "kalite": {k: measured[k] for k in ("dogrulanmis_is_basina_usd", "dogrulanmis_is_basina_token", "toplam_token",
                                             "token_bilinmeyen", "ilk_tur_gecen", "ilk_tur_olculen", "dogrulanan")},
        # this month's performance per role (the İK card): the same measure as Ozet.md / Kalite, over the month's rows
        "bu_ay_rol_kalite": [{"rol": rol, **{k: v for k, v in karne._rounded(karne._measure(
            [i["row"] for i in mon if "row" in i and i["rol"] == rol], events)).items()
            if k in ("is_sayisi", "ilk_tur_gecen", "ilk_tur_olculen", "dogrulanan", "dogrulanmis_is_basina_usd",
                     "dogrulanmis_is_basina_token")}}
            for rol in ROLE_ORDER if any(i["rol"] == rol and "row" in i for i in mon)],
        # plan "Sonraki iş (9)" step 2 (the İK card): this month's jobs per specialisation, open ones included; ""
        # = jobs from before the specialisation
        "bu_ay_uzmanlik": _uzmanliklar(mon),
        "en_pahali": [{k: i[k] for k in ("not", "baslik", "proje", "usd", "token", "acik")} for i in top],
        "butce": {"calisan": len(running), "harcanan_usd": round(spent, 6),
                  "harcanan_token": sum(known) if known else None, "token_bilinen": len(known),
                  "butce_usd": round(sum(r["butce"] for r in budgets), 6) if budgets else None,
                  "dikkat": sorted(flagged, key=lambda r: r["not"])},
    }


# --- İdari işler (GET /api/idari): office operations, read-only, cached ---

_idari = {"at": 0.0, "data": None}
IDARI_TTL = 30.0  # seconds: the plist and the log are read at most this often


def _size(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size


def _obsidian(problem):
    """{sorun, python}: whether this start could not read the vault, and the python binary to allow in Full Disk Access
    (structured: the problem's free text names the vault's home path, which the page never shows)."""
    if not problem:
        return {"sorun": False, "python": None}
    python = problem.get("python") if isinstance(problem, dict) else None
    return {"sorun": True, "python": python if isinstance(python, str) and python else None}


def idari(cfg, sunucu, vault_problem, agents_dir=None, log_dir=None, clock=None):
    """{sunucu, limitler, otomatik_baslatma, obsidian, gunluk}: the server start, the office limits of ofis.json, whether
    the login autostart plist is installed (a file read; launchctl is never run here), the Obsidian access problem of
    this start (None = none), and the server log's size (bytes; None when there is no log). Base names only."""
    import time
    import autostart
    import dispatcher
    now = (clock or time.monotonic)()
    if _idari["data"] is not None and now - _idari["at"] < IDARI_TTL:
        return {**_idari["data"], "sunucu": sunucu, "obsidian": _obsidian(vault_problem)}
    agents = agents_dir or autostart.AGENTS_DIR
    logs = log_dir or autostart.LOG_DIR
    plist = autostart.plist_path(agents)
    installed = os.path.lexists(plist) and autostart.is_ours(plist)
    run, per, queued = dispatcher.limits(cfg)
    data = {"limitler": {"max_running": run, "max_running_per_project": per, "max_queued_per_project": queued,
                         "max_bekleyen_onay": dispatcher.onay_siniri(cfg)},
            "otomatik_baslatma": {"kurulu": bool(installed), "dosya": os.path.basename(plist)},
            "gunluk": {"dosya": autostart.LOG_NAME, "boyut": _size(os.path.join(logs, autostart.LOG_NAME)),
                       "yedek_boyut": _size(os.path.join(logs, autostart.LOG_NAME + ".1"))}}
    _idari.update(at=now, data=data)
    return {**data, "sunucu": sunucu, "obsidian": _obsidian(vault_problem)}
