"""Delivery of messages to the CEO background session (the owner's chat, decision answers, post-office notices).

The CEO is the background session named cfg["ceo_session"] whose cwd is this folder. CeoController is a
channel.Channel with the CEO's file names: its full sessionId in durum/ceo.json, the queue in
durum/ceo-queue.jsonl, ambiguous deliveries in durum/ceo-unconfirmed.jsonl and delivered keyed notices in
durum/ceo-sent.txt. Unlike a project session, the CEO is started when it does not exist yet.
See channel.py for the start / stop+resume / queue rules.
Every message to the CEO ends with the reminder line "(<Owner>'e Türkçe ve sade yaz.)" — with ofis.json dil "en"
"(Reply to <Owner> in plain English.)" — (bin/sahip.py hatirlatma, with the owner's name from ofis.json sahip_adi): a resumed session does not re-read CLAUDE.md, and the CEO once answered a
notice in English. The chat parser (transcript.py) hides that line again. A newly started CEO session also gets the
owner's name in its system text (ceo_system_prompt).

Rotation (owner decision 2026-11-14, ofis.json `ceo_yenileme`): a long-lived CEO session re-reads its whole context on every
call (~640K tokens measured: ≈ $0.30 a step warm, $4–5 a step when the prompt cache is cold). Right before a message is
delivered to an idle or dormant CEO (never while it is busy or at a permission prompt: those messages stay queued), the
controller starts a FRESH CEO session instead of resuming when
  (a) the context of its newest model call (input + cache read + cache creation tokens) is at least `baglam_esigi`,
  (b) it has been idle for at least `soguk_dk` minutes (the prompt cache is cold, so the switch costs nothing extra)
      and its context is at least `soguk_esik`, or
  (c) `gunluk` is on and the session began on an earlier day (office time zone) — once a day.
The first prompt of the new session is the server's handoff block (bin/devir.py, built by `devir_notu`, no model call)
followed by the message. Only after claude confirmed the new session (its launch line, or a unique new session of this
name in `claude agents`) is the old one stopped (`claude stop`, never rm) — and only when it is still idle. The record
durum/ceo.json keeps every id the CEO ever had (`session_ids`: the global Codex Stop hook skips the office sessions by
these ids or by OFIS_OTURUMU=1) and the rotations (`yenilemeler`: eski, yeni, zaman, neden; the page reads the earlier
sessions' chat and turns from them). Everything runs under the channel's delivery lock, so two deliveries never rotate
at once, and the new session's small context and today's start make a second rotation impossible right after.
Failure: a start that claude refused (an error, nothing delivered) falls back to the normal resume of the old session
with the plain message — no message is lost; a start that timed out is ambiguous like any launch (never re-sent, logged
as unconfirmed). Either way the old session is never stopped, the event is logged and no rotation is tried again for
RETRY_ROTATION seconds. Without `ceo_yenileme.acik: true` (or without `ayarlar`) the CEO behaves exactly as before.

Forced rotation (`python3 bin/ofis.py ceo-yenile`, e.g. after CLAUDE.md or the message protocol changed): the command
only writes the flag file durum/ceo-yenile. The next delivery to an idle or dormant CEO then rotates with reason "elle"
exactly as above (also when `ceo_yenileme` is off), and the flag is removed once a CEO session was started (rotated or,
with no session yet, started fresh). A failed rotation keeps the flag; the next attempt follows RETRY_ROTATION.

Instructions changed (reason "talimat"): a resumed session keeps the CLAUDE.md it started with, so after CLAUDE.md
changed it could refuse a message in the new protocol. Every CEO start records the SHA-256 of this folder's CLAUDE.md
(`talimat_ozeti` in durum/ceo.json, `talimat_ozeti()`); before a delivery to an idle or dormant CEO a different current
hash rotates exactly like "elle" (also when `ceo_yenileme` is off). A record without a hash (written before this rule)
only gets the current hash, without a rotation, so a deploy causes no extra one; a missing CLAUDE.md never rotates.

Rate limit: a project session runs as the same OS user and could keep re-creating durum/ceo-yenile (or touching
CLAUDE.md) to make the office start CEO sessions over and over. So neither forced reason is taken within
ZORLA_ARALIK seconds of the last successful rotation with reason "elle" or "talimat"; the flag file is kept and a changed
hash stays different, so the rotation happens on the first delivery after that.
"""
import hashlib
import json
import os
import secrets
import tempfile
import threading
from datetime import datetime

import claude_cli
import devir
import dil
import model_durum
import sahip
import transcript
from channel import (GRACE_SECONDS, RETRY_SECONDS, STALE_TURN_SECONDS, Channel,  # noqa: F401 (re-exported)
                     ChannelUnavailable, _Busy, _live, _same_dir)

DEFAULTS = {"baglam_esigi": 150_000, "soguk_esik": 60_000, "soguk_dk": 55, "gunluk": True}
RETRY_ROTATION = 600.0  # seconds without a new rotation attempt after one failed
MAX_IDS = 60            # session ids kept in durum/ceo.json
MAX_ROTATIONS = 50      # rotation entries kept in durum/ceo.json (more than a busy day's)
NEDEN_METNI = {"baglam": "bağlam eşiği aşıldı", "soguk": "önbellek soğumuştu", "gunluk": "yeni gün",
               "elle": "elle istendi", "talimat": "ofisin talimatları (CLAUDE.md) değişti"}
ZORLANMIS = ("elle", "talimat")  # forced reasons: rate-limited by ZORLA_ARALIK
ZORLA_ARALIK = 600.0  # seconds after a successful forced rotation before the next forced one
YENILE_DOSYASI = "ceo-yenile"  # durum/ceo-yenile: `ofis.py ceo-yenile` asks for one fresh CEO session (reason "elle")


def yenile_iste(durum_dir, stamp):
    """Writes the flag durum/ceo-yenile (the same file `ofis.py ceo-yenile` writes) unless it is there: the next
    delivery to an idle or dormant CEO starts a fresh session. Used when the display language changes on the Ayarlar
    tab (the system text and the reminder line follow ofis.json `dil`). -> True when it was written now."""
    path = os.path.join(durum_dir, YENILE_DOSYASI)
    if os.path.lexists(path):
        return False
    os.makedirs(durum_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".ceo-yenile.", suffix=".tmp", dir=durum_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"istendi": stamp, "neden": "dil"}, f)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return True


def rotation_settings(cfg):
    """The rotation settings of ofis.json `ceo_yenileme` with defaults, or None when it is off (missing, not an
    object, or `acik` not true)."""
    raw = (cfg or {}).get("ceo_yenileme") if isinstance(cfg, dict) else None
    if not isinstance(raw, dict) or raw.get("acik") is not True:
        return None

    def num(key, low):
        v = raw.get(key)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= low else DEFAULTS[key]
    return {"baglam_esigi": int(num("baglam_esigi", 1000)), "soguk_esik": int(num("soguk_esik", 0)),
            "soguk_dk": float(num("soguk_dk", 1)), "gunluk": raw.get("gunluk", True) is not False}


def talimat_ozeti(root):
    """The SHA-256 (hex) of <root>/CLAUDE.md, or None when it cannot be read."""
    try:
        with open(os.path.join(root, "CLAUDE.md"), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def _office_tz(cfg):
    """The office zone (ofis.json ofis_sahnesi.saat_dilimi, else the system's local zone: bin/model_durum.py)."""
    return model_durum.office_tz(model_durum.saat_dilimi(cfg))

CeoUnavailable = ChannelUnavailable



def ceo_system_prompt(name, dil_kodu="tr"):
    """The CEO's system text with the owner's name (ofis.json sahip_adi) in the display language (ofis.json dil).
    The Turkish one is written in Turkish on purpose: the CEO answered in English even with CLAUDE.md and a
    per-message reminder; likewise the English one is in English. A background session records its system prompt at
    start and reuses it on every resume, so this only takes effect for a newly started CEO session (a language change
    on the Ayarlar tab asks for one: yenile_iste)."""
    if dil_kodu == "en":
        return (
            f"You are {name}'s Office CEO. The office owner's name is {name}; \"the owner\" in CLAUDE.md is {name}, "
            f"address them by name. Every reply you write to {name} must be in English, without exception: also your "
            f"replies to {name}'s messages (prompts starting with [Sahip · …]), to decision answers and to [Ofis · "
            "sistem] notices. Write plainly and briefly; no jargon. The office's protocol words, notes, job briefs, "
            "vault notes and commands stay as CLAUDE.md says (Turkish where it says so); only your replies to the owner "
            "are English. Leave code, commands and file names as they are."
        )
    return (
        f"Sen {sahip.ek(name, 'in')} Ofis CEO'susun. Ofisin sahibinin adı {name}; CLAUDE.md'deki \"the owner\" odur, "
        f"ona adıyla hitap et. {sahip.ek(name, 'e')} yazdığın her cevap Türkçe olmalı: {sahip.ek(name, 'in')} "
        "mesajlarına ([Sahip · …] ile başlayan istemler), karar cevaplarına ve [Ofis · sistem] bildirimlerine verdiğin "
        "cevaplar dahil, istisnasız. Sade ve kısa yaz; teknik terim ve kelime kelime çeviri kullanma (ör. 'vault' "
        "yerine 'Obsidian'daki notlar'). Kod, komut ve dosya adlarını olduğu gibi bırak."
    )


class CeoController(Channel):
    def __init__(self, cli, root, name, durum_dir, projects_dir, **kwargs):
        super().__init__(cli, root, name, durum_dir, projects_dir,
                         id_file=os.path.join(durum_dir, "ceo.json"),
                         queue_file=os.path.join(durum_dir, "ceo-queue.jsonl"),
                         unconfirmed_file=os.path.join(durum_dir, "ceo-unconfirmed.jsonl"),
                         sent_file=os.path.join(durum_dir, "ceo-sent.txt"),
                         allow_start=True, label="CEO", **kwargs)
        self.start_args = ["--append-system-prompt", ceo_system_prompt(sahip.ad(), dil.kod())]  # refreshed at every start
        self.yenile_dosyasi = os.path.join(durum_dir, YENILE_DOSYASI)
        self.ayarlar = None     # callable -> ofis.json as it is now (App.current_config); None = no rotation
        self.devir_notu = None  # callable(neden, kuyruk, kimlik) -> the handoff block (bin/devir.py); None = no rotation
        self.olay = None        # callable(text): the server's event record (OFIS/Sunucu), optional
        self._rotate_after = 0.0  # clock(): no rotation attempt before this (after a failed one)
        self._rotating = threading.Event()  # set while a rotation runs (status() says busy then anyway)

    # --- the record: every id and every rotation survive each write ---

    def _write_record(self, record):
        """Like Channel._write_record, but `session_ids` (every id the CEO ever had, also through a start that first
        records only a short id), `yenilemeler` and `baslangic` (when the current session began) are carried over."""
        old = self._read_record()
        ids = [i for i in old.get("session_ids") or [] if transcript.valid_session_id(i)]
        if transcript.valid_session_id(old.get("session_id")) and old["session_id"] not in ids:
            ids.append(old["session_id"])
        record = dict(record)
        sid = record.get("session_id")
        if transcript.valid_session_id(sid) and sid not in ids:
            ids.append(sid)
        if ids:
            record["session_ids"] = ids[-MAX_IDS:]
        for key in ("yenilemeler", "baslangic", "devir_kimlikleri", "talimat_ozeti"):
            if key not in record and key in old:
                record[key] = old[key]
        os.makedirs(os.path.dirname(self.id_file), exist_ok=True)
        tmp = f"{self.id_file}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.id_file)

    def _update_record(self, **fields):
        self._write_record(dict(self._read_record(), **fields))

    def rotations(self):
        """The recorded rotations, oldest first: [{eski, yeni, zaman, neden}]."""
        items = self._read_record().get("yenilemeler")
        return [r for r in items if isinstance(r, dict)] if isinstance(items, list) else []

    def handoff_ids(self):
        """The handoff block ids the server wrote (transcript.verify_handoffs)."""
        items = self._read_record().get("devir_kimlikleri")
        return [k for k in items if isinstance(k, str) and len(k) == 16] if isinstance(items, list) else []

    def earlier_ids(self, limit=3):
        """The ids of the sessions the CEO was rotated away from, newest last (at most `limit`): the page shows their
        chat and turns before the current session's."""
        current = self.session_id()
        out = []
        for r in self.rotations():
            sid = r.get("eski")
            if transcript.valid_session_id(sid) and sid != current and sid not in out:
                out.append(sid)
        return out[-limit:] if limit else out  # limit None: every recorded one (the day's spending totals)

    def _event(self, text):
        if self.olay:
            try:
                self.olay(text)
            except Exception:  # noqa: BLE001 — the record is optional; delivery goes on
                pass

    # --- rotation ---

    def context_tokens(self, sid=None):
        """The context size (tokens) of the CEO's newest model call, or None when unknown."""
        sid = sid or self.session_id()
        if not transcript.valid_session_id(sid):
            return None
        found = transcript.last_context(transcript.transcript_path(self.projects_dir, self.root, sid))
        return found["token"] if found else None

    def _began(self, sid, path):
        """When the session began (epoch seconds): the record's `baslangic` for this id, else the transcript's first
        record, else None."""
        record = self._read_record()
        if record.get("session_id") == sid and isinstance(record.get("baslangic"), str):
            try:
                return datetime.fromisoformat(record["baslangic"]).timestamp()
            except ValueError:
                pass
        return transcript.first_time(path)

    def _last_forced(self):
        """When the last rotation with a forced reason (ZORLANMIS) happened (epoch seconds), or None."""
        for r in reversed(self.rotations()):
            if r.get("neden") in ZORLANMIS and isinstance(r.get("zaman"), str):
                try:
                    return datetime.fromisoformat(r["zaman"]).timestamp()
                except ValueError:
                    continue
        return None

    def _forced_allowed(self):
        last = self._last_forced()
        return last is None or self.wallclock() - last >= ZORLA_ARALIK

    def _instructions_changed(self):
        """True when the CEO session's recorded CLAUDE.md hash differs from the current one (never without either)."""
        recorded = self._read_record().get("talimat_ozeti")
        current = talimat_ozeti(self.root)
        return isinstance(recorded, str) and bool(recorded) and current is not None and recorded != current

    def _record_instructions_once(self):
        """A record written before the hash existed gets the current hash, without a rotation."""
        if "talimat_ozeti" in self._read_record():
            return
        current = talimat_ozeti(self.root)
        if current is not None:
            self._update_record(talimat_ozeti=current)

    def rotation_reason(self, sid):
        """"elle", "talimat", "baglam", "soguk", "gunluk" or None (see the module doc)."""
        cfg = None
        if self.ayarlar is not None:
            try:
                cfg = self.ayarlar()
            except Exception:  # noqa: BLE001 — no readable settings: no rotation
                cfg = None
        if self.devir_notu is None or not transcript.valid_session_id(sid):
            return None
        if self._forced_allowed():
            if os.path.exists(self.yenile_dosyasi):
                return "elle"
            if self._instructions_changed():
                return "talimat"
        ayar = rotation_settings(cfg)
        if ayar is None:
            return None
        path = transcript.transcript_path(self.projects_dir, self.root, sid)
        found = transcript.last_context(path)
        tokens = found["token"] if found else 0
        if tokens >= ayar["baglam_esigi"]:
            return "baglam"
        now = self.wallclock()
        if found and found.get("zaman") is not None and tokens >= ayar["soguk_esik"] and \
                now - found["zaman"] >= ayar["soguk_dk"] * 60:
            return "soguk"
        if ayar["gunluk"]:
            began = self._began(sid, path)
            tz = _office_tz(cfg)
            if began is not None and datetime.fromtimestamp(began, tz).date() < datetime.fromtimestamp(now, tz).date():
                return "gunluk"
        return None

    def sahip_adi(self):
        """The owner's name from the running settings (ofis.json sahip_adi; the file itself without `ayarlar`)."""
        cfg = None
        if self.ayarlar is not None:
            try:
                cfg = self.ayarlar()
            except Exception:  # noqa: BLE001 — unreadable settings: the file's (or the default) name
                cfg = None
        return sahip.ad(cfg if isinstance(cfg, dict) else None)

    def dil(self):
        """The display language from the running settings (ofis.json dil; the file itself without `ayarlar`)."""
        cfg = None
        if self.ayarlar is not None:
            try:
                cfg = self.ayarlar()
            except Exception:  # noqa: BLE001 — unreadable settings: the file's (or the default) language
                cfg = None
        return dil.kod(cfg if isinstance(cfg, dict) else None)

    def _start(self, text):
        self.start_args = ["--append-system-prompt", ceo_system_prompt(self.sahip_adi(), self.dil())]
        before = self._read_record()
        ozet = talimat_ozeti(self.root)  # read before the start: the new session reads this CLAUDE.md (or a newer one)
        warning = super()._start(text)
        if ozet is not None:
            self._update_record(talimat_ozeti=ozet)
        try:  # a fresh session reads the current CLAUDE.md: a forced rotation is done
            os.unlink(self.yenile_dosyasi)
        except OSError:
            pass
        record = self._read_record()
        changed = (record.get("short_id"), record.get("session_id")) != (before.get("short_id"),
                                                                           before.get("session_id"))
        if changed and (record.get("short_id") or record.get("session_id")):
            self._update_record(baslangic=datetime.fromtimestamp(self.wallclock()).isoformat(timespec="seconds"))
        return warning

    def _send(self, text, st):
        if st["state"] in ("idle", "dormant"):
            self._record_instructions_once()
        if st["state"] in ("idle", "dormant") and self.clock() >= self._rotate_after:
            reason = self.rotation_reason(st["session_id"])
            if reason:
                done, warning = self._rotate(text, st, reason)
                if done:
                    return warning
        return super()._send(text, st)

    def _rotate(self, text, st, reason):
        """Starts a fresh CEO session with the handoff block + text. Returns (True, warning) when the message went to
        the new session (or may have: a timeout re-raises like any launch), (False, None) when the caller must resume
        the old session instead."""
        old = st["session_id"]
        self._rotating.set()
        try:
            try:
                queued = sum(1 for i in self._pending() if i.get("text") != text)  # the others still waiting
                kimlik = secrets.token_hex(8)
                # recorded before the start: the page hides only a handoff block whose id the server wrote
                self._update_record(devir_kimlikleri=(self.handoff_ids() + [kimlik])[-MAX_ROTATIONS:])
                handoff = self.devir_notu(reason, queued, kimlik)
            except Exception as e:  # noqa: BLE001 — no handoff, no rotation: the old session goes on
                handoff = None
                self._event(f"CEO oturumu yenilenemedi: devir notu yazılamadı ({type(e).__name__}); eski oturum "
                            "devam ediyor")
            if not isinstance(handoff, str) or not handoff.strip():
                self._rotate_after = self.clock() + RETRY_ROTATION
                return False, None
            before_record = self._read_record()
            try:
                before = {a.get("sessionId") for a in self.cli.agents(fresh=True)}
            except claude_cli.ClaudeError:
                before = set()
            try:
                warning = self._start(devir.birlestir(handoff, text))
            except claude_cli.ClaudeTimeout:
                self._rotate_after = self.clock() + RETRY_ROTATION
                self._delivered_at, self._seen_busy = self.clock(), False  # it may be running now
                self._event("CEO oturumu yenilenirken claude zaman aşımına uğradı; mesaj tekrar gönderilmedi, eski "
                            "oturum durdurulmadı")
                raise
            except claude_cli.ClaudeError as e:
                self._rotate_after = self.clock() + RETRY_ROTATION
                self._event(f"CEO oturumu yenilenemedi ({e}); mesaj eski oturuma iletiliyor")
                return False, None
            new = self._confirmed_new(before, before_record)
            self._delivered_at, self._seen_busy = self.clock(), False
            self.last_error = f"warning: {warning}" if warning else None
            if new is None:
                # claude accepted the message but the new session could not be identified: keep the old id, never
                # stop the old session; the message is not re-sent
                self._rotate_after = self.clock() + RETRY_ROTATION
                self._write_record(before_record)
                self._event("CEO yeni oturumu doğrulanamadı; eski oturum durdurulmadı, kayıt değişmedi")
                return True, warning
            entry = {"eski": old, "yeni": new, "zaman": datetime.fromtimestamp(self.wallclock()).isoformat(
                timespec="seconds"), "neden": reason}
            self._update_record(yenilemeler=(self.rotations() + [entry])[-MAX_ROTATIONS:])
            self._stop_old(old, st["state"])
            self._event(f"CEO yeni oturumla devam ediyor ({NEDEN_METNI.get(reason, reason)}); devir notu verildi")
            return True, warning
        finally:
            self._rotating.clear()

    def _confirmed_new(self, before, before_record):
        """The new session's id (full, or the short id claude printed) once claude confirmed it, else None."""
        record = self._read_record()
        sid = record.get("session_id")
        if transcript.valid_session_id(sid) and sid != before_record.get("session_id"):
            return sid
        if not transcript.valid_session_id(sid) and transcript.valid_session_id(record.get("short_id")):
            return record["short_id"]
        try:  # an unrecognised launch line: a unique new session of this name and folder still confirms it
            agents = self.cli.agents(fresh=True)
        except claude_cli.ClaudeError:
            return None
        found = [a["sessionId"] for a in agents if self._matches(a) and a.get("sessionId") not in before
                 and transcript.valid_session_id(a.get("sessionId"))]
        if len(found) != 1:
            return None
        self._write_record({"session_id": found[0], "name": self.name, "cwd": self.root,
                            "recorded_at": datetime.now().isoformat(timespec="seconds"),
                            "baslangic": datetime.fromtimestamp(self.wallclock()).isoformat(timespec="seconds")})
        return found[0]

    def _stop_old(self, old, state):
        """Stops the old session after the new one is confirmed: only when it is still listed as idle (a dormant one is
        not running; a busy one is never interrupted). Never rm."""
        if state != "idle":
            return
        try:
            agent = next((a for a in _live(self.cli.agents(fresh=True)) if a.get("sessionId") == old), None)
            if agent is None:
                return
            if agent.get("status") != "idle":
                self._event("eski CEO oturumu boşta değil; durdurulmadı")
                return
            self.cli.stop(old[:8])
        except claude_cli.ClaudeError as e:
            self._event(f"eski CEO oturumu durdurulamadı ({e})")

    def status(self):
        st = super().status()
        if self._rotating.is_set():
            st["state"] = "busy"
        return st

    def deliver(self, text):
        return super().deliver(with_reminder(text, self.sahip_adi(), self.dil()))

    def enqueue(self, text, key):
        return super().enqueue(with_reminder(text, self.sahip_adi(), self.dil()), key)


def with_reminder(text, name=None, dil_kodu="tr"):
    """text + newline + the reminder line with the owner's name in the display language (once: a reminder under any
    name, in either language, already there is kept). Anything that is not a non-empty string is left for the checks."""
    if not isinstance(text, str) or not text.strip() or sahip.hatirlatmayi_sil(text) != text:
        return text
    return text.rstrip("\n") + "\n" + sahip.hatirlatma(name, dil_kodu)
