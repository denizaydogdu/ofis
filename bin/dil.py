"""The office's display language (ofis.json `dil`: "tr" | "en", default "tr"; the Ayarlar tab's Genel).

Only the texts the page shows are translated, at the place they are put into an API answer (bin/state.py, the stop
reasons of the progress line; bin/kullanim.py; bin/limitler.py `sayfa`; bin/sistem.py; the Ayarlar errors). Codes stay
codes; vault notes, CEO notices, session contracts and `ofis.py` output stay Turkish. Strings are keyed by their
Turkish source: t(text, cfg) returns it as is in Turkish and the English entry of EN in English (the Turkish text when
an entry is missing). `{name}` placeholders are filled from keyword arguments in both languages; an English entry may
be a tuple (one, other), chosen by n (1 = one). test/test_dil.py checks the entries against the t("…") literals.

kod(cfg): cfg's valid `dil` when cfg is a dict, else this repository's ofis.json (cached by the file's identity), else
"tr". Standard library only.
"""
import json
import os
import re
import threading

import yasaklar

KEY = "dil"
DILLER = ("tr", "en")
VARSAYILAN = "tr"
ADLAR = {"tr": "Türkçe", "en": "English"}
CONFIG = None  # a test may point this module at a file of its own; None = yasaklar.ofis_json()

_kilit = threading.Lock()
_onbellek = {}
_YER = re.compile(r"\{(\w+)\}")


def dogrula(value):
    """[] for a usable language code, else the (Turkish source) error."""
    if value not in DILLER:
        return [Metin("Dil şunlardan biri olmalı: {diller}.", "dil", diller=", ".join(DILLER))]
    return []


def _dosyadan():
    path = CONFIG or yasaklar.ofis_json()
    try:
        st = os.stat(path)
    except OSError:
        return None
    kimlik = (st.st_ino, st.st_size, st.st_mtime_ns)
    with _kilit:
        hit = _onbellek.get(path)
        if hit and hit[0] == kimlik:
            return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    value = data.get(KEY) if isinstance(data, dict) else None
    code = value if value in DILLER else None
    with _kilit:
        _onbellek[path] = (kimlik, code)
    return code


def kod(cfg=None):
    """"tr" or "en". cfg may be the config dict, a language code, or None (the file in force)."""
    if isinstance(cfg, str):
        return cfg if cfg in DILLER else VARSAYILAN
    if isinstance(cfg, dict):
        value = cfg.get(KEY)
        return value if value in DILLER else VARSAYILAN
    return _dosyadan() or VARSAYILAN


def _doldur(text, values):
    if not values:
        return text
    return _YER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def t(text, cfg=None, **values):
    """text in the display language of cfg (see kod), placeholders filled."""
    source = str(text)
    out = source
    if kod(cfg) == "en":
        e = EN.get(source)
        if isinstance(e, str):
            out = e
        elif isinstance(e, tuple) and len(e) == 2:
            out = e[0] if values.get("n") == 1 else e[1]
    return _doldur(out, values)


def N_(text):
    """Marks a Turkish module constant for translation without translating it (t() it where it is drawn)."""
    return text


class Metin(str):
    """A Turkish display text built from a template (`sablon`) and its values, so it can be translated later: it is
    the filled Turkish string itself (comparisons and tests see that), plus `alan` (the form field it belongs to,
    "" = none)."""

    def __new__(cls, sablon, alan="", **values):
        self = super().__new__(cls, _doldur(sablon, values))
        self.sablon = sablon
        self.degerler = values
        self.alan = alan
        return self


def cevir(text, cfg=None):
    """A Metin (or a plain string) in the display language."""
    if isinstance(text, Metin):
        return t(text.sablon, cfg, **{k: cevir(v, cfg) if isinstance(v, Metin) else v for k, v in text.degerler.items()})
    return t(text, cfg)


# English entries, keyed by the Turkish source. Grouped by the module that uses them.
EN = {
    # bin/dil.py
    "Dil şunlardan biri olmalı: {diller}.": "Language must be one of: {diller}.",

    # bin/ayarlar.py (the Ayarlar tab's errors)
    "'{ad}' adı ayrılmış; başka bir ad seçin.": "The name '{ad}' is reserved; pick another one.",
    "'{ad}' adında bir proje yok.": "There is no project called '{ad}'.",
    "'{ad}' adında bir proje zaten var.": "A project called '{ad}' already exists.",
    "'{ad}' projesinin açık bir akışı var ({grup}); önce kapanmalı.":
        "Project '{ad}' has an open workflow ({grup}); it has to close first.",
    "'{ad}' projesinin zamanlanmış işi var ({ad_zaman}); önce zamanlanmış iş kaldırılmalı (duraklatılmış olsa da).":
        "Project '{ad}' has a scheduled job ({ad_zaman}); remove the schedule first (even a paused one).",
    "'{ad}' projesinin {n} açık işi var (sırada ya da çalışıyor); önce bitmeli ya da iptal edilmeli.":
        ("Project '{ad}' has {n} open job (queued or running); it has to finish or be cancelled first.",
         "Project '{ad}' has {n} open jobs (queued or running); they have to finish or be cancelled first."),
    "'{ad}' yerleşik bir proje; silinemez (klasörü değiştirilebilir).":
        "'{ad}' is a built-in project; it cannot be removed (its folder can change).",
    "Açıklama en çok {sinir} karakter olabilir.": "The description can be at most {sinir} characters.",
    "Açıklama tek satır olmalı.": "The description must be a single line.",
    "Açıklama zorunlu.": "A description is required.",
    "Bilinmeyen alan: {alanlar}": "Unknown field: {alanlar}",
    "Bilinmeyen alan: {alanlar} (model katmanları Ayarlar'dan değiştirilmez)":
        "Unknown field: {alanlar} (model tiers are not changed from Settings)",
    "Bu klasör bilgisayarın kişisel ayar klasörlerinden biri (Library ya da ev klasöründeki gizli klasörler, ör. .ssh, "
    ".claude); proje olarak eklenemez.":
        "This folder is one of the computer's personal settings folders (Library or a hidden folder in your home "
        "folder, e.g. .ssh, .claude); it cannot be a project.",
    "Bu klasör ofisin dışında tutulan bir yolda; proje olarak eklenemez.":
        "This folder is on a path kept outside the office; it cannot be a project.",
    "Bu klasör zaten '{ad}' projesinin klasörü.": "This folder already belongs to project '{ad}'.",
    "Domainler en çok {sayi} host adından oluşan bir liste olmalı.": "Domains must be a list of at most {sayi} host names.",
    "Domainler yalnız host adı olmalı (ornek.com gibi; https:// ya da yol yok): {liste}":
        "Domains must be host names only (like example.com; no https:// and no path): {liste}",
    "E-posta domaini yalnız host adı olmalı (ornek.com gibi).": "The mail domain must be a host name only (like example.com).",
    "Hassas yollar": "Sensitive paths",
    "Klasör bulunamadı: {yol}": "Folder not found: {yol}",
    "Klasör yolu boş olamaz.": "The folder path cannot be empty.",
    "Klasör yolu geçersiz.": "The folder path is not valid.",
    "Klasör yolu tam yol olmalı (/ ya da ~ ile başlamalı).": "The folder path must be a full path (starting with / or ~).",
    "Klasör yolu ve açıklama boş bırakılamaz.": "The folder path and the description cannot be empty.",
    "Klasör şu an değiştirilemez: {neden}": "The folder cannot change right now: {neden}",
    "Ofis adı boş olamaz.": "The office name cannot be empty.",
    "Ofis adı en çok {sinir} karakter olabilir.": "The office name can be at most {sinir} characters.",
    "Ofis adı tek satırlık düz metin olmalı.": "The office name must be one line of plain text.",
    "Ofis adı ya da senin adın gönderilmeli.": "Send the office name or your name.",
    "Proje adı küçük harf, rakam ve tireden oluşmalı, harf ya da rakamla başlamalı (en çok 40).":
        "The project name must use lower-case letters, digits and dashes, and start with a letter or digit (at most 40).",
    "Proje alanları bir nesne olmalı.": "The project fields must be an object.",
    "Proje klasörü Obsidian kasası olamaz, onun içinde ya da üstünde olamaz.":
        "The project folder cannot be the Obsidian vault, inside it or above it.",
    "Proje klasörü Ofis'in kendi klasörü olamaz, onun içinde ya da üstünde olamaz.":
        "The project folder cannot be the Office's own folder, inside it or above it.",
    "Proje kuralları en çok {sinir} karakterlik düz metin olabilir.": "Project rules can be at most {sinir} characters of plain text.",
    "Proje kuralları metin olmalı.": "Project rules must be text.",
    "Sistem bölümü bir nesne olmalı (domainler, eposta_domaini, cloudflare).":
        "The system section must be an object (domainler, eposta_domaini, cloudflare).",
    "Sistem bölümünde bilinmeyen alan: {alanlar}": "Unknown field in the system section: {alanlar}",
    "Sorumlu bölümü bir nesne olmalı (dur_sor, asla, teslim).": "The lead section must be an object (dur_sor, asla, teslim).",
    "Sorumlu bölümünde bilinmeyen alan: {alanlar}": "Unknown field in the lead section: {alanlar}",
    "Sorumlu · {ad}": "Lead · {ad}",
    "cloudflare true ya da false olmalı.": "cloudflare must be true or false.",
    "islem şunlardan biri olmalı: {liste}": "islem must be one of: {liste}",
    "ofis.json bir JSON nesnesi değil; ayarlar yazılmadı": "ofis.json is not a JSON object; settings were not written",
    "ofis.json'da projects bölümü yok; ayarlar yazılmadı.": "ofis.json has no projects section; settings were not written.",
    "proje bir nesne olmalı (ad, path, description, …).": "proje must be an object (ad, path, description, …).",
    "{ad} bir liste olmalı.": "{ad} must be a list.",
    "{ad} en çok {sayi} satır olabilir.": "{ad} can have at most {sayi} lines.",
    "{ad} yalnız metin satırlarından oluşmalı.": "{ad} must contain text lines only.",
    "{ad}: her satır en çok {sinir} karakterlik tek bir satır olmalı.": "{ad}: each line must be one line of at most {sinir} characters.",

    # bin/sahip.py (the owner's name)
    "Adın boş olamaz.": "Your name cannot be empty.",
    "Adın en çok {sinir} karakter olabilir.": "Your name can be at most {sinir} characters.",
    "Adın harfle başlamalı; yalnız harf, rakam, boşluk, nokta, kesme işareti ve tire içerebilir (köşeli parantez, · ya "
    "da satır sonu olamaz).":
        "Your name must start with a letter and may contain only letters, digits, spaces, dots, apostrophes and "
        "dashes (no brackets, · or line breaks).",
    "Bu ad ofisin kendi konuşmacılarına ayrılmış (Ofis, CEO, Müdür); başka bir ad yaz.":
        "This name is reserved for the office's own speakers (Ofis, CEO, Müdür); pick another one.",

    # bin/server.py
    "Ayar dosyası bilinmiyor; ayarlar bu sunucudan değiştirilemez.":
        "The settings file is unknown; settings cannot be changed from this server.",
    "ayarlar yazılamadı: {tur}": "settings could not be written: {tur}",
    "geçersiz istek": "invalid request",

    # bin/npc_sohbet.py (NPC chat)
    "NPC sohbeti ayarı bir nesne olmalı (acik, saatlik_sinir).": "The NPC chat setting must be an object (acik, saatlik_sinir).",
    "NPC sohbeti · açık/kapalı seçimi true ya da false olmalı.": "NPC chat · on/off must be true or false.",
    "NPC sohbeti · bilinmeyen alan: {alanlar}": "NPC chat · unknown field: {alanlar}",
    "NPC sohbeti · saatlik sınır 1 ile {sinir} arasında bir tam sayı olmalı.":
        "NPC chat · the hourly limit must be a whole number from 1 to {sinir}.",
    "NPC sohbeti kapalı; Ayarlar'daki Genel bölümünden açılabilir.":
        "NPC chat is off; you can turn it on under Settings › General.",
    "Bu karakterle sohbet edilemez.": "You can't chat with this character.",
    "Biraz bekle: şu an başka bir soruyu cevaplıyorum.": "One moment: I'm answering another question right now.",
    "Soru boş olamaz.": "The question cannot be empty.",
    "Soru en çok {sinir} karakter olabilir.": "The question can be at most {sinir} characters.",
    "Saatte en çok {saatlik} soru sorulabilir; yaklaşık {dakika} dakika sonra yeniden dene.":
        "At most {saatlik} questions an hour; try again in about {dakika} minutes.",
    "Şu an cevap veremiyorum ({neden}); biraz sonra yeniden dene.": "I can't answer right now ({neden}); try again a bit later.",
    "boş cevap": "empty answer",
    "claude cevap vermedi, çıkış {kod}": "claude did not answer, exit {kod}",
    "claude çalıştırılamadı": "claude could not be run",
    "istem geçersiz": "invalid prompt",
    "zaman aşımı": "timed out",
    "Sekreter": "Secretary",
    "Muhasebeci": "Accountant",
    "İdari işler sorumlusu": "Office manager",
    "İK sorumlusu": "HR lead",
    "Ofis psikoloğu": "Office psychologist",
    "Ofis doktoru": "Office doctor",
    "IT sorumlusu": "IT lead",
    "Ar-Ge uzmanı": "R&D specialist",
    "Güvenlik görevlisi": "Security guard",
    "Yazılım Müdürü": "Software Manager",
    "QA Müdürü": "QA Manager",
    "Analist Müdürü": "Analyst Manager",
    "IT Müdürü": "IT Manager",
    "{proje} proje sorumlusu": "{proje} project lead",

    # bin/state.py (the progress line's reason words)
    "başlatılamadı": "could not start",
    "iptal": "cancelled",
    "kullanım sınırı doldu": "usage limit reached",
    "takıldı": "stuck",
    "çağrı sınırı": "call limit",
    "üst katmana taşındı": "moved up a tier",

    # bin/limitler.py (the usage pill on the page) and bin/kullanim.py (its popup)
    "Haftalık": "Weekly",
    "5 saatlik": "5-hour",
    "5 saat": "5 h",
    "{etiket} %{yuzde}": "{etiket} {yuzde}%",
    "{etiket} sıfırlandı": "{etiket} reset",
    "{etiket} sınır %{yuzde}": "{etiket} limit {yuzde}%",
    "{etiket} sınır sıfırlandı (yeni değer henüz ölçülmedi)": "{etiket} limit reset (no new reading yet)",
    "{head} · {zaman}": "{head} · {zaman}",
    "{head} · {zaman} sıfırlanır": "{head} · resets {zaman}",
    "{zaman} ölçüldü": "measured {zaman}",
    "{zaman} yenilenir": "resets {zaman}",
    "ölçüm zamanı bilinmiyor": "reading time unknown",
    "sıfırlandı (yeni değer henüz ölçülmedi)": "reset (no new reading yet)",
    "1 dakikadan az kaldı": "less than a minute left",
    "{dk} dk sonra": "in {dk} min",
    "{sa} sa sonra": "in {sa} h",
    "{sa} sa {dk} dk sonra": "in {sa} h {dk} min",
    "{gun} gün sonra": ("in {gun} day", "in {gun} days"),
    "{gun} gün {sa} sa sonra": "in {gun} d {sa} h",
    "Bu pencere: {beri}": "This window: {beri}",
    "Son 5 saat": "Last 5 hours",
    "Son 7 gün": "Last 7 days",
    "Son ölçüm eski: değerler bir Claude oturumu açılınca yenilenir.":
        "The last reading is old: the values refresh when a Claude session is opened.",
    "Plan yüzdesi tokenlarla birebir orantılı değildir (önbellekten okunan tokenlar daha hafif sayılır); bu liste "
    "kimin en çok kullandığını gösterir, kesin payını değil.":
        "The plan percentage is not exactly proportional to tokens (tokens read from cache count less); this list "
        "shows who used the most, not their exact share.",
    "Müdür ve hakem çağrıları": "Manager and referee calls",
    "Geliştirici oturumu": "Developer session",
    "Ofis dışı diğer oturumlar": "Other sessions outside the office",
    "Ofis işi": "Office job",
    "{proje} işi": "{proje} job",
    "Daha küçük {n} kullanım": ("{n} smaller use", "{n} smaller uses"),
    "Toplam": "Total",
    "{token} · API karşılığı bilinmiyor": "{token} · API equivalent unknown",
    "çıktı {token}": "output {token}",

    # bin/sistem.py (the Sunucu odası: /api/sistem)
    "Tarayıcılar": "Browsers",
    "Claude oturumları": "Claude sessions",
    "Ofis sunucusu": "Office server",
    "Diğer": "Other",
    "şarj oluyor": "charging",
    "pilde": "on battery",
    "dolu": "full",
    "adaptörde": "on power adapter",
    "adaptör": "power adapter",
    "pil": "battery",
    "bilinmiyor": "unknown",
    "hiç konteyner çalışmıyor": "no container is running",
    "{n} konteyner boşta": ("{n} container is idle", "{n} containers are idle"),
    "Docker {gb} bellek tutuyor ama {what}. Kullanmıyorsan Docker Desktop'ı kapatmak belleği rahatlatır (karar {sahip}).":
        "Docker holds {gb} of memory but {what}. If you're not using it, quitting Docker Desktop frees memory "
        "({sahip} call).",
    "{n} Claude oturumu boşta duruyor ({gb} bellek). İşi biten oturumları kapatmayı düşünebilirsin (karar {sahip}).":
        ("{n} Claude session is idle ({gb} of memory). You could close sessions whose work is done ({sahip} call).",
         "{n} Claude sessions are idle ({gb} of memory). You could close sessions whose work is done ({sahip} call)."),
    "Disk %{yuzde} dolu ({gb} boş). Gereksiz büyük dosyaları temizlemeyi düşünebilirsin (karar {sahip}).":
        "The disk is {yuzde}% full ({gb} free). You could clean up large files you don't need ({sahip} call).",
    "Bellek sıkışık (macOS bellek baskısı {baski}). En çok bellek tutan grubu kapatmak bilgisayarı rahatlatır "
    "(karar {sahip}).":
        "Memory is tight (macOS memory pressure {baski}). Closing the group that holds the most memory helps "
        "({sahip} call).",
    "kritik": "critical",
    "yüksek": "high",
    "{ad} bir süredir %{cpu} işlemci kullanıyor. Gerekmiyorsa kapatmayı düşünebilirsin (karar {sahip}).":
        "{ad} has been using {cpu}% CPU for a while. If you don't need it, you could close it ({sahip} call).",
    "Tarayıcılar %{cpu} işlemci kullanıyor ve ofis sayfası açık. Sayfayı ?hafif=1 ile açmak bilgisayarı serinletir.":
        "Browsers are using {cpu}% CPU and the office page is open. Opening the page with ?hafif=1 keeps the "
        "computer cooler.",
    "adres çözülemedi": "address not resolved",
    "sertifika doğrulanamadı": "certificate not verified",
    "bağlanılamadı": "could not connect",
    "açılmıyor": "not opening",
    "sertifikası bitiyor": "certificate expiring",
    "DNS değişti": "DNS changed",
    "Domain listesi henüz yok — Ar-Ge ilk çalışmasında soracak": "No domain list yet — R&D will ask on its first run",
    # bin/danisman.py: why a job gets the advisor (the job card's "Danışman: … — <reason>", via bin/state.py)
    "zor iş: geliştirme akışının kod adımı": "hard job: the code step of a development workflow",
    "zor iş: bir üst katmana taşınan iş": "hard job: moved up a tier",
    "zor iş: kod incelemesi değişikliği yüksek riskli buldu": "hard job: the code review rated the change high risk",
    "zor iş: kod incelemesi düzeltme istedi": "hard job: the code review asked for fixes",
    "zor iş: Kontrol geçmedi, yeniden çalışıyor": "hard job: the check failed, working on it again",
    "danışman denemesi (B kolu)": "advisor trial (arm B)",
    "kalıcı eşleme": "permanent mapping",
}
