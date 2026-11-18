"""The office's settings (plan "Ayarlar sayfası", phase 1.1–1.4): the one writer of ofis.json, the project validation,
the delete guard, the live refresh of the running server's cfg and the data of GET / POST /api/ayarlar.

- yaz(config_path, degistir): reads ofis.json, applies degistir(data) and replaces the file atomically (temp file 0600
  in the same folder + os.replace; key order, indentation and the trailing newline kept). It runs under the job lock
  (jobs.locked: one flock per office, re-entrant within a thread), so the server and `ofis.py cevapla` never write
  over each other. degistir may raise Hata: nothing is written then. danisman._write_config and
  model_secimi.set_override are thin callers of it.
- proje_dogrula(cfg, ad, alanlar, mevcut): the plain-Turkish error list of a project entry (empty = valid). Name: one
  regex for the whole office (AD, = launch.PROJECT_NAME), `ofis` is reserved, unique. Folder: expanded and resolved,
  an existing folder, not a forbidden path (`guvenlik.yasak_yollar`), not inside / above the office's own folder or the vault (the parent
  of vault_ofis), not ~/Library or a hidden folder right under home (or inside one), not another project's same
  folder (nested ones are allowed). Folders are compared by file identity (st_dev, st_ino), never by their spelling:
  macOS folders are case-insensitive. The stored path is in the file system's own case (fcntl F_GETPATH). Fields: description (required, one line, ≤ 300), notes, hassas_yollar,
  sorumlu {dur_sor, asla, teslim}, sistem {domainler (host names only), eposta_domaini, cloudflare}; anything else
  (also `tiers`: the model cards' path only) is refused.
- proje_sil_engeli(cfg, ad, durum_dir): why a project cannot be removed (a queued / running job, a schedule that is
  not removed, a workflow not in akis.FINAL_STATES, a built-in project), else None. acik_is_engeli: the job and
  workflow part alone, which also blocks a folder change.
- islem(config_path, durum_dir, govde): one POST /api/ayarlar body applied to the file (proje-ekle, proje-guncelle,
  proje-sil, genel); a refusal raises Hata(status, errors) and writes nothing. Deleting never touches the vault notes.
  A folder change is refused (409) under open work and drops the project from ucretsiz_denetci_projeler in the same
  write (ucretsiz_denetci_kaldirildi in the result).
- Yenileyici: takes the file's projects, ucretsiz_denetci_projeler, ofis_adi and sahip_adi (and the advisor keys, bin/danisman.py
  refresh) into the running cfg — the one dict every server thread shares. cfg["projects"] is replaced by a new dict
  (one assignment), so a reader iterating the old one keeps a consistent view. A project removed from the file while
  it still has open work (proje_sil_engeli) is kept and logged once. mtime-gated; the post office calls it every
  tick, the server after its own write (zorla=True); while a project is held, the unchanged file is read again every
  TUTULAN_TEKRAR_TIK ticks (~60 s), so the project leaves once its work ends.
"""
import json
import os
import re
import shlex
import tempfile
import threading

import jobs
import launch
import sahip

ROOT = launch.ROOT
AD = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
AYRILMIS = ("ofis",)  # the office's own pseudo-project (bin/ofis.py, bin/gunsonu.py OFIS_PROJE)
YERLESIK = ("arge",)  # built in: the Ar-Ge room's workspace (bin/arge.py PROJE); its folder may change, never removed
VARSAYILAN_OFIS_ADI = "Ofis"
OFIS_ADI_SINIRI = 40
ACIKLAMA_SINIRI = 300
NOTLAR_SINIRI = 2000
YOL_SINIRI = 1024
HASSAS_SAYISI = 20
HASSAS_SINIRI = 200
SORUMLU_SAYISI = 12
SORUMLU_SINIRI = 400
DOMAIN_SAYISI = 20
ALANLAR = ("path", "description", "notes", "hassas_yollar", "sorumlu", "sistem")
SORUMLU_ALANLARI = ("dur_sor", "asla", "teslim")
SISTEM_ALANLARI = ("domainler", "eposta_domaini", "cloudflare")
ISLEMLER = ("proje-ekle", "proje-guncelle", "proje-sil", "genel")
ACIK_DURUMLAR = ("sirada",) + jobs.ACTIVE_STATUSES
TUTULAN_TEKRAR_TIK = 20  # post-office ticks (3 s each, ~60 s) between re-reads of an unchanged file while one is held
CANLI_ANAHTARLAR = ("ucretsiz_denetci_projeler", "ofis_adi", "sahip_adi")  # top-level keys the refresh takes along
# bin/sistem.py DOMAIN: a lower-case host name
HOST = re.compile(r"(?=.{1,253}$)(?:(?!-)[a-z0-9-]{1,63}(?<!-)\.)+[a-z]{2,63}")
KONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f  ‪-‮⁦-⁩]")
SATIR = re.compile(r"[\r\n]")


class Hata(Exception):
    """A refused settings change: an HTTP status (400 invalid, 404 unknown project, 409 not now) and the plain
    Turkish error list."""

    def __init__(self, durum, hatalar):
        self.durum = durum
        self.hatalar = list(hatalar) if isinstance(hatalar, (list, tuple)) else [str(hatalar)]
        super().__init__("; ".join(self.hatalar))


# --- the one writer ---

def yaz(config_path, degistir):
    """Reads ofis.json, applies degistir(data) and replaces the file atomically under the job lock. Returns data."""
    with jobs.locked():
        with open(config_path, encoding="utf-8") as f:
            raw = f.read()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise Hata(409, ["ofis.json bir JSON nesnesi değil; ayarlar yazılmadı"])
        degistir(data)
        text = json.dumps(data, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else "")
        folder = os.path.dirname(os.path.abspath(config_path))
        fd, tmp = tempfile.mkstemp(prefix=".ofis.", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, config_path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    return data


# --- validation ---

def ofis_adi(cfg):
    value = (cfg or {}).get("ofis_adi")
    return value.strip() if isinstance(value, str) and value.strip() else VARSAYILAN_OFIS_ADI


def ofis_adi_dogrula(value):
    if not isinstance(value, str) or not value.strip():
        return ["Ofis adı boş olamaz."]
    if KONTROL.search(value) or SATIR.search(value):
        return ["Ofis adı tek satırlık düz metin olmalı."]
    if len(value.strip()) > OFIS_ADI_SINIRI:
        return [f"Ofis adı en çok {OFIS_ADI_SINIRI} karakter olabilir."]
    return []


def _gercek(path):
    return os.path.realpath(os.path.expanduser(path))


def _kimlik(path):
    """The folder's file identity (st_dev, st_ino), or None when it does not exist. macOS folders are case-insensitive
    and may be reached through links, so the office compares folders by identity, never by their spelling."""
    try:
        st = os.stat(path)
    except (OSError, ValueError, TypeError):
        return None
    return st.st_dev, st.st_ino


def _zincir(real):
    """[(path, identity)] of real and of every folder above it, up to /."""
    out, path = [], real
    while True:
        out.append((path, _kimlik(path)))
        parent = os.path.dirname(path)
        if parent == path:
            return out
        path = parent


def _icinde(real, folder):
    """True when real is folder or inside it (by identity, walking up from real)."""
    k = _kimlik(folder)
    return k is not None and any(x == k for _, x in _zincir(real))


def _kanonik(real):
    """The folder as the file system spells it (its real case; macOS fcntl F_GETPATH), else real unchanged."""
    try:
        import fcntl
    except ImportError:
        return real
    if not hasattr(fcntl, "F_GETPATH"):
        return real
    try:
        fd = os.open(real, os.O_RDONLY)
    except (OSError, ValueError, TypeError):
        return real
    try:
        raw = fcntl.fcntl(fd, fcntl.F_GETPATH, b"\0" * 1024)
    except OSError:
        return real
    finally:
        os.close(fd)
    path = os.fsdecode(raw.split(b"\0", 1)[0])
    return path if os.path.isabs(path) and _kimlik(path) is not None and _kimlik(path) == _kimlik(real) else real


def _vault_koku(cfg):
    v = (cfg or {}).get("vault_ofis")
    if not isinstance(v, str) or not v.strip():
        return None
    return os.path.dirname(_gercek(v.strip()).rstrip(os.sep)) or None


KISISEL = ("Library",)  # besides every hidden folder right under the home folder (~/.claude, ~/.ssh, ~/.config, …)


def _kisisel_klasor(real):
    """True when real is a per-user folder the office keeps out (or inside one): ~/Library or a hidden folder right
    under the home folder."""
    home = os.path.realpath(os.path.expanduser("~"))
    home_k = _kimlik(home)
    if home_k is None or os.path.dirname(home) == home:
        return False
    named = {_kimlik(os.path.join(home, n)) for n in KISISEL} - {None}
    chain = _zincir(real)
    for (path, k), (_, parent_k) in zip(chain, chain[1:]):
        if parent_k == home_k:
            return os.path.basename(path).startswith(".") or k in named
    return False


def _yol_hatalari(cfg, path, mevcut):
    if not isinstance(path, str) or not path.strip():
        return ["Klasör yolu boş olamaz."]
    if len(path) > YOL_SINIRI or KONTROL.search(path) or SATIR.search(path):
        return ["Klasör yolu geçersiz."]
    expanded = os.path.expanduser(path.strip())
    if not os.path.isabs(expanded):
        return ["Klasör yolu tam yol olmalı (/ ya da ~ ile başlamalı)."]
    real = os.path.realpath(expanded)
    if launch.is_forbidden_path(real) or launch.is_forbidden_path(expanded) or \
            launch.is_forbidden_path(_kanonik(real)):
        return ["Bu klasör ofisin dışında tutulan bir yolda; proje olarak eklenemez."]
    if not os.path.isdir(real):
        return [f"Klasör bulunamadı: {real}"]
    # by identity, both ways: the candidate inside the folder, and the folder inside the candidate
    root = os.path.realpath(ROOT)
    if _icinde(real, root) or _icinde(root, real):
        return ["Proje klasörü Ofis'in kendi klasörü olamaz, onun içinde ya da üstünde olamaz."]
    vault = _vault_koku(cfg)
    if vault and (_icinde(real, vault) or _icinde(vault, real)):
        return ["Proje klasörü Obsidian kasası olamaz, onun içinde ya da üstünde olamaz."]
    if _kisisel_klasor(real):
        return ["Bu klasör bilgisayarın kişisel ayar klasörlerinden biri (Library ya da ev klasöründeki gizli "
                "klasörler, ör. .ssh, .claude); proje olarak eklenemez."]
    k = _kimlik(real)
    for name, entry in list(((cfg or {}).get("projects") or {}).items()):
        if name == mevcut or not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            continue
        if _kimlik(_gercek(entry["path"])) == k:  # the same folder (nested ones stay allowed, as before)
            return [f"Bu klasör zaten '{name}' projesinin klasörü."]
    return []


def _metin_listesi(value, sayi, sinir, ad):
    """A list of one-line strings (or one string where allowed by the caller) -> errors."""
    if not isinstance(value, list):
        return [f"{ad} bir liste olmalı."]
    if len(value) > sayi:
        return [f"{ad} en çok {sayi} satır olabilir."]
    for item in value:
        if not isinstance(item, str):
            return [f"{ad} yalnız metin satırlarından oluşmalı."]
        if len(item) > sinir or KONTROL.search(item) or SATIR.search(item):
            return [f"{ad}: her satır en çok {sinir} karakterlik tek bir satır olmalı."]
    return []


def _alan_hatalari(alanlar, ekleniyor):
    errors = []
    unknown = sorted(k for k in alanlar if k not in ALANLAR)
    if unknown:
        errors.append("Bilinmeyen alan: " + ", ".join(map(str, unknown)) +
                      (" (model katmanları Ayarlar'dan değiştirilmez)" if "tiers" in unknown else ""))
    if ekleniyor or "description" in alanlar:
        d = alanlar.get("description")
        if not isinstance(d, str) or not d.strip():
            errors.append("Açıklama zorunlu.")
        elif SATIR.search(d.strip()) or KONTROL.search(d):
            errors.append("Açıklama tek satır olmalı.")
        elif len(d.strip()) > ACIKLAMA_SINIRI:
            errors.append(f"Açıklama en çok {ACIKLAMA_SINIRI} karakter olabilir.")
    if "notes" in alanlar:
        n = alanlar["notes"]
        if not isinstance(n, str):
            errors.append("Proje kuralları metin olmalı.")
        elif len(n) > NOTLAR_SINIRI or KONTROL.search(n.replace("\t", " ")):
            errors.append(f"Proje kuralları en çok {NOTLAR_SINIRI} karakterlik düz metin olabilir.")
    if "hassas_yollar" in alanlar:
        errors += _metin_listesi(alanlar["hassas_yollar"], HASSAS_SAYISI, HASSAS_SINIRI, "Hassas yollar")
    if "sorumlu" in alanlar:
        s = alanlar["sorumlu"]
        if not isinstance(s, dict):
            errors.append("Sorumlu bölümü bir nesne olmalı (dur_sor, asla, teslim).")
        else:
            extra = sorted(k for k in s if k not in SORUMLU_ALANLARI)
            if extra:
                errors.append("Sorumlu bölümünde bilinmeyen alan: " + ", ".join(map(str, extra)))
            for key in SORUMLU_ALANLARI:
                if key in s:
                    value = [s[key]] if isinstance(s[key], str) else s[key]
                    errors += _metin_listesi(value, SORUMLU_SAYISI, SORUMLU_SINIRI, f"Sorumlu · {key}")
    if "sistem" in alanlar:
        s = alanlar["sistem"]
        if not isinstance(s, dict):
            errors.append("Sistem bölümü bir nesne olmalı (domainler, eposta_domaini, cloudflare).")
        else:
            extra = sorted(k for k in s if k not in SISTEM_ALANLARI)
            if extra:
                errors.append("Sistem bölümünde bilinmeyen alan: " + ", ".join(map(str, extra)))
            if "domainler" in s:
                d = s["domainler"]
                if not isinstance(d, list) or len(d) > DOMAIN_SAYISI:
                    errors.append(f"Domainler en çok {DOMAIN_SAYISI} host adından oluşan bir liste olmalı.")
                else:
                    bad = [x for x in d if not isinstance(x, str) or not HOST.fullmatch(x.strip().lower())]
                    if bad:
                        errors.append("Domainler yalnız host adı olmalı (ornek.com gibi; https:// ya da yol yok): " +
                                      ", ".join(str(x)[:60] for x in bad[:3]))
            e = s.get("eposta_domaini")
            if e not in (None, "") and (not isinstance(e, str) or not HOST.fullmatch(e.strip().lower())):
                errors.append("E-posta domaini yalnız host adı olmalı (ornek.com gibi).")
            if "cloudflare" in s and not isinstance(s["cloudflare"], bool):
                errors.append("cloudflare true ya da false olmalı.")
    return errors


def proje_dogrula(cfg, ad, alanlar, mevcut=None):
    """The errors of a project entry (plain Turkish; [] = valid). mevcut: the project being updated (its own name and
    folder are not duplicates); alanlar then holds only the fields that change."""
    errors = []
    projects = (cfg or {}).get("projects") if isinstance((cfg or {}).get("projects"), dict) else {}
    if not isinstance(ad, str) or not AD.fullmatch(ad):
        errors.append("Proje adı küçük harf, rakam ve tireden oluşmalı, harf ya da rakamla başlamalı (en çok 40).")
    elif ad in AYRILMIS:
        errors.append(f"'{ad}' adı ayrılmış; başka bir ad seçin.")
    elif mevcut is None and ad in projects:
        errors.append(f"'{ad}' adında bir proje zaten var.")
    if not isinstance(alanlar, dict):
        return errors + ["Proje alanları bir nesne olmalı."]
    errors += _alan_hatalari(alanlar, ekleniyor=mevcut is None)
    if mevcut is None or "path" in alanlar:
        errors += _yol_hatalari(cfg, alanlar.get("path"), mevcut)
    return errors


def yol_yazimi(path):
    """The folder as it is written into ofis.json: resolved, in the file system's own case, the home folder as ~."""
    real = _kanonik(_gercek(path.strip()))
    home = _kanonik(os.path.realpath(os.path.expanduser("~")))
    if real.startswith(home.rstrip(os.sep) + os.sep):
        return "~" + real[len(home.rstrip(os.sep)):]
    return real


def _temiz_alanlar(alanlar):
    """The validated fields as stored: strings stripped; an empty value means "remove the key" (None)."""
    out = {}
    for key, value in alanlar.items():
        if key == "path":
            out[key] = yol_yazimi(value)
        elif key in ("description", "notes"):
            out[key] = value.strip() or None
        elif key == "hassas_yollar":
            out[key] = [x.strip() for x in value if x.strip()] or None
        elif key == "sorumlu":
            s = {}
            for k in SORUMLU_ALANLARI:
                v = value.get(k)
                lines = [x.strip() for x in ([v] if isinstance(v, str) else v or []) if x.strip()]
                if lines:
                    s[k] = lines[0] if isinstance(v, str) else lines
            out[key] = s or None
        elif key == "sistem":
            s = {}
            doms = [x.strip().lower() for x in value.get("domainler") or []]
            if doms:
                s["domainler"] = list(dict.fromkeys(doms))
            if isinstance(value.get("eposta_domaini"), str) and value["eposta_domaini"].strip():
                s["eposta_domaini"] = value["eposta_domaini"].strip().lower()
            if isinstance(value.get("cloudflare"), bool):
                s["cloudflare"] = value["cloudflare"]
            out[key] = s or None
    return out


# --- what blocks a delete ---

def acik_is_sayilari(vault):
    """{project: number of queued / running jobs} from the job notes."""
    out = {}
    try:
        notes = jobs.list_jobs(vault, (jobs.QUEUED, jobs.ACTIVE))
    except (OSError, jobs.JobError):
        return out
    for job in notes:
        p = job.meta.get("proje")
        if job.meta.get("durum") in ACIK_DURUMLAR and isinstance(p, str) and p:
            out[p] = out.get(p, 0) + 1
    return out


def acik_is_engeli(cfg, ad, durum_dir=None):
    """Open work of project `ad` (plain Turkish), or None: a queued / running job, or a workflow not final. It blocks
    both a delete and a folder change (a running job's Kontrol and a workflow's diffs use the project's folder)."""
    vault = (cfg or {}).get("vault_ofis")
    if isinstance(vault, str) and vault.strip():
        n = acik_is_sayilari(os.path.expanduser(vault)).get(ad, 0)
        if n:
            return f"'{ad}' projesinin {n} açık işi var (sırada ya da çalışıyor); önce bitmeli ya da iptal edilmeli."
    if durum_dir:
        import akis  # lazy: akis imports danisman, which imports this module
        for state in akis.list_states(durum_dir):
            if state.get("proje") == ad and state.get("durum") not in akis.FINAL_STATES:
                return f"'{ad}' projesinin açık bir akışı var ({state.get('grup')}); önce kapanmalı."
    return None


def proje_sil_engeli(cfg, ad, durum_dir=None):
    """Why project `ad` cannot be removed now (plain Turkish), or None."""
    if ad in YERLESIK:
        return f"'{ad}' yerleşik bir proje; silinemez (klasörü değiştirilebilir)."
    reason = acik_is_engeli(cfg, ad, durum_dir)
    if reason:
        return reason
    if durum_dir:
        import zamanla  # lazy: zamanla imports kontrol and launch
        for name in zamanla.names(durum_dir):
            defn = zamanla.load(durum_dir, name)
            if defn and defn.get("proje") == ad and defn.get("durum") != zamanla.REMOVED:
                return (f"'{ad}' projesinin zamanlanmış işi var ({name}); önce zamanlanmış iş kaldırılmalı "
                        "(duraklatılmış olsa da).")
    return None


# --- one POST body ---

def _anahtarlar(govde, izinli):
    extra = sorted(str(k) for k in govde if k not in izinli)
    if extra:
        raise Hata(400, ["Bilinmeyen alan: " + ", ".join(extra)])


def islem(config_path, durum_dir, govde):
    """Applies one POST /api/ayarlar body to ofis.json. Returns {islem, ad} (ad: the project, "" for genel).
    Raises Hata (nothing written)."""
    if not isinstance(govde, dict) or govde.get("islem") not in ISLEMLER:
        raise Hata(400, ["islem şunlardan biri olmalı: " + ", ".join(ISLEMLER)])
    kind = govde["islem"]
    if kind == "genel":
        # the office's name and the owner's name (bin/sahip.py); at least one, each validated, written together
        _anahtarlar(govde, ("islem", "ofis_adi", "sahip_adi"))
        if "ofis_adi" not in govde and "sahip_adi" not in govde:
            raise Hata(400, ["Ofis adı ya da senin adın gönderilmeli."])
        errors = (ofis_adi_dogrula(govde["ofis_adi"]) if "ofis_adi" in govde else []) + \
            (sahip.dogrula(govde["sahip_adi"]) if "sahip_adi" in govde else [])
        if errors:
            raise Hata(400, errors)
        values = {k: govde[k].strip() for k in ("ofis_adi", "sahip_adi") if k in govde}
        yaz(config_path, lambda data: data.update(values))
        return {"islem": kind, "ad": ""}
    if kind == "proje-sil":
        _anahtarlar(govde, ("islem", "ad"))
        ad = govde.get("ad")

        def sil(data):
            projects = data.get("projects") if isinstance(data.get("projects"), dict) else {}
            if not isinstance(ad, str) or ad not in projects:
                raise Hata(404, [f"'{ad}' adında bir proje yok."])
            reason = proje_sil_engeli(data, ad, durum_dir)
            if reason:
                raise Hata(409, [reason])
            del projects[ad]
            free = data.get("ucretsiz_denetci_projeler")
            if isinstance(free, list) and ad in free:
                data["ucretsiz_denetci_projeler"] = [p for p in free if p != ad]
        yaz(config_path, sil)
        return {"islem": kind, "ad": ad}
    _anahtarlar(govde, ("islem", "proje"))
    proje = govde.get("proje")
    if not isinstance(proje, dict):
        raise Hata(400, ["proje bir nesne olmalı (ad, path, description, …)."])
    ad = proje.get("ad")
    alanlar = {k: v for k, v in proje.items() if k != "ad"}
    ucretsiz_kaldirildi = []

    def ekle_ya_da_guncelle(data):
        projects = data.get("projects")
        if not isinstance(projects, dict):
            raise Hata(409, ["ofis.json'da projects bölümü yok; ayarlar yazılmadı."])
        if kind == "proje-guncelle":
            if not isinstance(ad, str) or ad not in projects or not isinstance(projects[ad], dict):
                raise Hata(404, [f"'{ad}' adında bir proje yok."])
            errors = proje_dogrula(data, ad, alanlar, mevcut=ad)
            if errors:
                raise Hata(400, errors)
            entry = projects[ad]
            old_path = entry.get("path") if isinstance(entry.get("path"), str) else ""
            if "path" in alanlar and (not old_path or
                                      _kimlik(_gercek(alanlar["path"].strip())) != _kimlik(_gercek(old_path))):
                # a new folder: never under open work (Kontrol and the workflow diffs use the folder)
                reason = acik_is_engeli(data, ad, durum_dir)
                if reason:
                    raise Hata(409, ["Klasör şu an değiştirilemez: " + reason])
                # the free outside reviewers were the owner's decision for the old folder: off for the new one
                free = data.get("ucretsiz_denetci_projeler")
                if isinstance(free, list) and ad in free:
                    data["ucretsiz_denetci_projeler"] = [p for p in free if p != ad]
                    ucretsiz_kaldirildi.append(ad)
        else:
            errors = proje_dogrula(data, ad, alanlar)
            if errors:
                raise Hata(400, errors)
            entry = projects[ad] = {}
        for key, value in _temiz_alanlar(alanlar).items():
            if value is None:
                entry.pop(key, None)
            else:
                entry[key] = value
        if not entry.get("path") or not entry.get("description"):  # path and description stay required
            raise Hata(400, ["Klasör yolu ve açıklama boş bırakılamaz."])
        # the order of a new entry: path first, then the rest as written
        if kind == "proje-ekle":
            projects[ad] = {k: entry[k] for k in ALANLAR if k in entry}
    yaz(config_path, ekle_ya_da_guncelle)
    out = {"islem": kind, "ad": ad}
    if kind == "proje-guncelle":
        out["ucretsiz_denetci_kaldirildi"] = bool(ucretsiz_kaldirildi)
    return out


# --- GET /api/ayarlar ---

def guven(path):
    """Claude Code's trust of a project folder (launch.folder_trusted: True / False / None unknown) and the command
    hint for an untrusted one ("" otherwise). The office never writes Claude's config."""
    try:
        real = _gercek(path)
    except (TypeError, ValueError):
        return None, ""
    trusted = launch.folder_trusted(real)
    return trusted, (f"cd {shlex.quote(real)} && claude" if trusted is False else "")


def ozet(cfg, durum_dir=None):
    """The GET /api/ayarlar body from the running cfg."""
    projects = (cfg or {}).get("projects") if isinstance((cfg or {}).get("projects"), dict) else {}
    vault = (cfg or {}).get("vault_ofis")
    counts = acik_is_sayilari(os.path.expanduser(vault)) if isinstance(vault, str) and vault.strip() else {}
    rows = []
    for ad, entry in list(projects.items()):
        if not isinstance(entry, dict):
            continue
        path = entry.get("path") if isinstance(entry.get("path"), str) else ""
        trusted, hint = guven(path) if path else (None, "")
        rows.append({
            "ad": ad, "path": path, "tam_yol": _gercek(path) if path else "",
            "description": entry.get("description") if isinstance(entry.get("description"), str) else "",
            "notes": entry.get("notes") if isinstance(entry.get("notes"), str) else "",
            "hassas_yollar": [x for x in entry.get("hassas_yollar") or [] if isinstance(x, str)]
            if isinstance(entry.get("hassas_yollar"), list) else [],
            "sorumlu": dict(entry["sorumlu"]) if isinstance(entry.get("sorumlu"), dict) else {},
            "sistem": dict(entry["sistem"]) if isinstance(entry.get("sistem"), dict) else {},
            "yerlesik": ad in YERLESIK, "acik_is_sayisi": counts.get(ad, 0), "guven": trusted, "ipucu": hint})
    return {"ofis_adi": ofis_adi(cfg), "sahip_adi": sahip.ad(cfg), "projeler": rows, "kurallar": {
        "ad_regex": AD.pattern, "ayrilmis": list(AYRILMIS), "yerlesik": list(YERLESIK),
        "aciklama_siniri": ACIKLAMA_SINIRI, "notlar_siniri": NOTLAR_SINIRI, "ofis_adi_siniri": OFIS_ADI_SINIRI,
        "sahip_adi_siniri": sahip.SINIR,
        "hassas_sayisi": HASSAS_SAYISI, "sorumlu_alanlari": list(SORUMLU_ALANLARI),
        "sistem_alanlari": list(SISTEM_ALANLARI), "alanlar": list(ALANLAR), "islemler": list(ISLEMLER)}}


ISLEM_METNI = {"proje-ekle": "eklendi", "proje-guncelle": "güncellendi", "proje-sil": "silindi"}


def bildirim(sonuc, cfg=None):
    """The CEO's one notice after a project change on the page, or None (genel). It carries no text typed on the
    page (the description stays in ofis.json and OFIS/Projeler/<P>.md): only the server's own words and the
    validated project name."""
    what = ISLEM_METNI.get(sonuc.get("islem"))
    if not what:
        return None
    ad = sonuc.get("ad")
    text = f"[Ofis · sistem]\nAyarlar sayfasından proje {what}: {ad}."
    if sonuc["islem"] == "proje-sil":
        return text + (" Bu projeye artık iş eklenemez; Obsidian'daki notları olduğu gibi duruyor. "
                       f"{sahip.e()} tek satırla söyle.")
    if sonuc.get("ucretsiz_denetci_kaldirildi"):
        text += (f" Klasörü değiştiği için bu projede ücretsiz dış denetçiler kapatıldı; yeniden açmak {sahip.in_()} "
                 "kararı.")
    return (text + f" Bu projeye iş eklemeden önce ofis.json'daki kaydını ve OFIS/Projeler/{ad}.md notunu oku. "
            f"{sahip.e()} tek satırla söyle.")


# --- the live refresh ---

class Yenileyici:
    """Takes ofis.json's live keys into the running cfg (see the module doc). One per server (the post office's)."""

    def __init__(self, cfg, config_path, durum_dir=None, log=None):
        self.cfg = cfg
        self.config_path = config_path
        self.durum_dir = durum_dir
        self.log = log or (lambda line: None)
        self.seen = None
        self.uyarilan = set()  # projects whose kept-on-removal line was logged
        self.tutulan = set()  # projects removed from the file but kept for their open work
        self._tik = 0  # unchanged-file calls since the last read, while something is held
        self._lock = threading.Lock()

    def yenile(self, zorla=False):
        """Returns {eklenen, guncellenen, silinen, tutulan} (project names; all empty when nothing was read)."""
        empty = {"eklenen": [], "guncellenen": [], "silinen": [], "tutulan": []}
        if not self.config_path:
            return empty
        with self._lock:
            try:
                mtime = os.stat(self.config_path).st_mtime_ns
            except OSError:
                return empty
            if mtime == self.seen and not zorla:
                # a held project leaves once its work ends: read the unchanged file again every ~minute meanwhile
                if not self.tutulan:
                    return empty
                self._tik += 1
                if self._tik < TUTULAN_TEKRAR_TIK:
                    return empty
            self._tik = 0
            try:
                with open(self.config_path, encoding="utf-8") as f:
                    fresh = json.load(f)
            except (OSError, ValueError):
                return empty  # mid-edit or broken: tried again on the next change
            if not isinstance(fresh, dict) or not isinstance(fresh.get("projects"), dict):
                self.seen = mtime
                self.log("ofis.json: projects bölümü okunamadı; çalışan ayarlar değişmedi")
                return empty
            self.seen = mtime
            changes = tazele(self.cfg, fresh, self.durum_dir, self.uyarilan, self.log)
            self.tutulan = set(changes["tutulan"])
            return changes


def tazele(cfg, fresh, durum_dir=None, uyarilan=None, log=None):
    """Applies a freshly read ofis.json to the running cfg (projects, the live top-level keys, the advisor keys)."""
    import danisman  # lazy: danisman imports this module
    danisman.refresh(cfg, fresh)
    old = cfg.get("projects") if isinstance(cfg.get("projects"), dict) else {}
    new = {name: entry for name, entry in fresh["projects"].items() if isinstance(entry, dict)}
    changes = {"eklenen": [n for n in new if n not in old],
               "guncellenen": [n for n in new if n in old and old[n] != new[n]], "silinen": [], "tutulan": []}
    for name in [n for n in old if n not in new]:
        reason = proje_sil_engeli(cfg, name, durum_dir) if name not in YERLESIK else None
        if reason:
            new[name] = old[name]
            changes["tutulan"].append(name)
            if uyarilan is not None and name not in uyarilan:
                uyarilan.add(name)
                if log:
                    log(f"ofis.json: '{name}' dosyadan çıkarıldı ama açık işi var; çalışan ofiste tutuluyor ({reason})")
        else:
            changes["silinen"].append(name)
    if uyarilan is not None:
        uyarilan.intersection_update(changes["tutulan"])
    cfg["projects"] = new  # one assignment: a reader holding the old dict keeps a consistent view
    for key in CANLI_ANAHTARLAR:
        if key in fresh:
            cfg[key] = fresh[key]
        else:
            cfg.pop(key, None)
    return changes
