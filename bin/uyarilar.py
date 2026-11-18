"""Guard-rails of `ofis.py ekle` / `akis` / `zamanla ekle` (B3 audit, owner decision 2026-11-12): deterministic checks of a
new job, no model call, no file access (the caller passes the Karne rows).

They only WARN: the job is still added and every warning is printed as `UYARI: …` (plain Turkish, the CEO reads it
and tells the owner). The one clear case is a refusal: a `kod` job whose Kontrol can never fail (kontrol_reddi) would close
code work without proof. Every other check is a heuristic and never blocks.

- kontrol_gucu(cmd): "kesin" when the command always exits 0 (true, :, exit 0, echo, pwd, a bare ls, git status, …,
  `… || true`, `…; true`), "zayif" when it only shows that a file exists (cat f, ls f, git rev-parse --verify x), ""
  otherwise (a real check, or a shell construct this parser does not follow: never guessed as trivial).
- ekle_uyarilari(): a change brief outside kod (P1), an open-ended kolay Hedef or a kolay job without Kontrol (P2), an
  explicit --model (P3), a budget far from the tier's observed spend (P4), a Kontrol that cannot fail (P5), a call
  limit (--cagri) far above the tier's or beyond what the budget can pay (P6).
- akis_uyarilari(): a review share below the observed cost of one Claude review (P7).
The Karne rows (karne._rows) count with their real cost, self-test (deneme) rows included: the money was spent.
"""
import re
import shlex

import launch

MIN_EVIDENCE = 3  # rows of the same project × tier × model before the spend checks speak
LOW_FACTOR = 1.2
HIGH_FACTOR = 50
CALL_FACTOR = 2
LONG_HEDEF = 500
CHANGE_TIERS = ("kolay", "genel")
REVIEW_KINDS = ("plan-inceleme", "kod-inceleme")
NOT_CLAUDE = ("", "heyet", "codex", "deniz")

KESIN, ZAYIF, GERCEK = "kesin", "zayif", ""
_RANK = {GERCEK: 0, ZAYIF: 1, KESIN: 2}
_BY_RANK = {v: k for k, v in _RANK.items()}
# tee exits 0 whatever it reads: without pipefail `… | tee log` always passes (review 2026-11-12)
ALWAYS = {"true", ":", "echo", "printf", "pwd", "date", "whoami", "hostname", "uname", "tee"}
EXISTS = {"cat", "ls", "wc", "head", "tail", "sort", "uniq", "stat", "file"}
OPAQUE = ("$(", "`", "<(", ">(")
OPAQUE_WORDS = {"if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case", "esac", "function",
                "bash", "sh", "zsh", "eval", "exec", "source", ".", "xargs", "env", "sudo", "time", "nohup", "!",
                "{", "}", "[[", "]]"}
GIT_SAFE_REV_PARSE = {"--is-inside-work-tree", "--abbrev-ref", "HEAD", "--show-toplevel", "--git-dir", "--short",
                      "--is-bare-repository"}
SEPARATORS = (";", "&&", "||", "|")
REDIRECT = re.compile(r"[<>&]*[<>][<>&]*")


def _norm(text):
    """Turkish-aware lower case (İ -> i, I -> ı) with the whitespace collapsed."""
    text = str(text or "").replace("İ", "i").replace("I", "ı").lower()
    return " ".join(text.split())


# --- Kontrol strength (P5) ---

def _split_words(cmd):
    lex = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""  # bash: `#` starts a comment only at a word's start (a#b is one word); handled by the caller
    return list(lex)


def _simple(words):
    """The strength of one simple command (its words, redirections removed)."""
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
        words = words[1:]
    if not words:
        return KESIN  # only assignments
    prog, args = words[0], words[1:]
    plain = [a for a in args if not a.startswith("-")]
    if prog == "exit":
        return KESIN if args == ["0"] else GERCEK
    if prog in ALWAYS:
        return KESIN
    if prog in EXISTS:
        if prog == "ls" and all(a in (".", "./") for a in plain):
            return KESIN
        return ZAYIF if plain else KESIN
    if prog == "git" and args:
        sub, rest = args[0], args[1:]
        flags = set(rest)
        if sub == "status":
            return KESIN
        if sub == "rev-parse":
            return KESIN if flags and flags <= GIT_SAFE_REV_PARSE else ZAYIF
        if sub in ("diff", "log", "branch"):
            if flags & {"--exit-code", "--quiet", "--check"}:
                return GERCEK
            return KESIN if not [a for a in rest if not a.startswith("-")] else ZAYIF
    return GERCEK


def _items(cmd):
    """[words, op, words, op, …] of a command line, or None for a construct this parser does not follow."""
    parts = _split_words(cmd)
    items, words, skip = [], [], False
    for i, part in enumerate(parts):
        if skip:
            skip = False
            continue
        if part in SEPARATORS:
            items += [words, part]
            words = []
            continue
        if part in ("&", "(", ")") or (part in OPAQUE_WORDS and not words):
            return None
        if REDIRECT.fullmatch(part):  # a redirection: drop it and its target (and a 2>&1 fd number before it)
            if words and words[-1].isdigit() and parts[i - 1] == words[-1]:
                words.pop()
            skip = True
            continue
        words.append(part)
    items.append(words)
    if any(isinstance(x, list) and not x for x in items):
        return None
    return items


def _errexit(words):
    """True for `set -e` (any short-flag cluster with e: -e, -eu, -euo), `set -o errexit` and any `trap`: an earlier
    failing command then decides the exit status, so the last command no longer does."""
    if not words:
        return False
    if words[0] == "trap":
        return True
    if words[0] != "set":
        return False
    args = words[1:]
    return any(a.startswith("-") and not a.startswith("--") and "e" in a[1:] for a in args) or "errexit" in args


def kontrol_gucu(cmd):
    """"kesin" (always exits 0), "zayif" (only shows that something exists) or "" (a real check or unknown)."""
    cmd = str(cmd or "").strip()
    # pipefail / PIPESTATUS: a pipeline's status is no longer only its last command's; `#`: a comment hides the rest
    # of a line from this parser, so it never guesses
    if not cmd or any(mark in cmd for mark in OPAQUE) or "pipefail" in cmd or "PIPESTATUS" in cmd or "#" in cmd:
        return GERCEK
    try:
        items = _items(cmd)
    except ValueError:  # unbalanced quotes
        return GERCEK
    if items is None or any(_errexit(x) for x in items if isinstance(x, list)):
        return GERCEK
    # a `;` list: its last and-or list decides
    last = []
    for x in items:
        last = [] if x == ";" else last + [x]
    # a pipeline's status is its last command's; then && keeps the weaker, || the stronger (left to right)
    value, op, pipe = None, None, []

    def fold(value, op, strength):
        if value is None:
            return strength
        return min(value, strength) if op == "&&" else max(value, strength)
    for x in last:
        if x in ("&&", "||"):
            value = fold(value, op, _RANK[_simple(pipe[-1])])
            op, pipe = x, []
        elif x != "|":
            pipe.append(x)
    value = fold(value, op, _RANK[_simple(pipe[-1])])
    return _BY_RANK[value]


def _short(text, limit=80):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def kontrol_reddi(tier, cmd):
    """The refusal text when a `kod` job's Kontrol always passes, else None (the one clear case)."""
    if tier != launch.KOD_TIER or kontrol_gucu(cmd) != KESIN:
        return None
    return (f"kod işinin Kontrolü hiç başarısız olamaz (`{_short(cmd)}`): kod işi kanıtsız kapanırdı. İşin sonucunu "
            "gerçekten sınayan bir komut yaz (ör. ilgili test komutu: pytest -q …, flutter test …)")


def kontrol_uyarisi(cmd):
    strength = kontrol_gucu(cmd)
    if strength == KESIN:
        return (f"Kontrol (`{_short(cmd)}`) her zaman geçer: işin sonucunu sınamıyor. İşin gerçek sonucunu denetleyen "
                "bir komut yaz (ör. test -s rapor.md && grep -q '…' rapor.md ya da istenen test komutu).")
    if strength == ZAYIF:
        return (f"Kontrol (`{_short(cmd)}`) yalnız bir şeyin var olduğunu gösterir, içeriğini sınamıyor. İşin "
                "sonucunu denetleyen bir koşul ekle (ör. grep -q '…' dosya ya da istenen test komutu).")
    return None


# --- the brief (P1, P2) ---

READ_ONLY = ("salt oku", "read-only", "read only", "do not edit", "değiştirme", "dokunma", "düzenleme yapma",
             "hiçbir dosya")
CHANGE_VERB = re.compile(r"(?<!\w)(düzelt|güncelle|değiştir|oluştur|kaldır|refactor|implement|uygula|yeniden yaz"
                         r"|ekle(?:yin|yip|\b)|sil(?:in|ip|\b)|taşı\b)")
CODE_FILE = re.compile(r"(?<![\w.])[\w./-]*\w\.(?:py|dart|kt|kts|swift|tsx?|jsx?|java|go|rs|rb|php|sh|gradle|ya?ml"
                       r"|json|toml|sql|xml|plist|html|s?css|cpp|[ch]|m)\b")
RUNS = re.compile(r"(?<!\w)(?:python3?|bash|sh|zsh|node|ruby|perl)\s+(?:-\S+\s+)*$")
JUDGEMENT = re.compile(r"(?<!\w)(araştır|analiz|değerlendir|öner|tasarla|incele)")


def change_reason(hedef):
    """Why a Hedef reads like a code change ("" when it does not, or when it says it is read-only)."""
    text = _norm(hedef)
    if any(mark in text for mark in READ_ONLY):
        return ""
    for found in CODE_FILE.finditer(text):
        if not RUNS.search(text[:found.start()]):  # a script the job only runs is not a change
            return f"bir kod dosyası ({found.group(0)})"
    found = CHANGE_VERB.search(text)
    if found:
        return f"bir değişiklik fiili (\"{found.group(1)}\")"
    return ""


# --- the checks ---

def _float(value):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _money(value):
    text = f"{value:.4f}" if value < 1 else f"{value:.2f}"
    return "$" + (text.rstrip("0").rstrip(".") or "0")


def _same(rows, project, tier, model):
    return [r for r in rows if r.get("Proje") == project and r.get("Katman") == tier and r.get("Model") == model
            and _float(r.get("Maliyet ($)")) is not None]


def ekle_uyarilari(cfg, project, tier, model, explicit_model, budget, brief, rows, call_limit=None):
    """The warnings (plain Turkish, no prefix) of a new job, in a fixed order."""
    out = []
    brief = brief or {}
    hedef = brief.get("hedef") or ""
    check = (brief.get("kontrol") or "").strip()
    if tier in CHANGE_TIERS:  # P1
        reason = change_reason(hedef)
        if reason:
            out.append(f"Hedef {reason} içeriyor ama iş {tier} katmanında: kod değiştiren iş kod katmanında olmalı "
                       "(çalıştırılabilir Kontrol ile). Salt okumaysa Hedef'e \"salt okuma, dosya değiştirme\" yaz.")
    if tier == "kolay":  # P2
        parts = []
        if len(hedef) >= LONG_HEDEF:
            parts.append(f"Hedef uzun ({len(hedef)} karakter)")
        found = JUDGEMENT.search(_norm(hedef))
        if found:
            parts.append(f"Hedef bir yargı istiyor (\"{found.group(1)}\")")
        if parts:
            out.append(" ve ".join(parts) + ": kolay iş açık uçlu olmamalı. Böyle bir iş genel katmana uygun.")
        if not check:
            out.append("kolay işin Kontrol yok: iş yalnız projenin sözüyle kapanır. Sonucu sınayan bir komut ekle.")
    if explicit_model:  # P3
        mapped = launch.tier_entry(cfg, project, tier)[0]
        if mapped and model == mapped:
            out.append(f"--model {model} verildi; bu, {tier} katmanı için eşlemeyle aynı model. Bayrak gereksiz ve iş "
                       "elle seçilmiş sayıldığı için karnede kanıt sayılmaz.")
        else:
            out.append(f"--model {model} elle verildi ({tier} katmanının eşlemesi: {mapped or '—'}); bu iş karnede "
                       "model için kanıt sayılmaz ve model denemesine (pilot) girmez.")
    same = _same(rows, project, tier, model)
    spend = _float(budget)
    if spend is not None and len(same) >= MIN_EVIDENCE:  # P4
        costs = [_float(r["Maliyet ($)"]) for r in same]
        top, mean = max(costs), sum(costs) / len(costs)
        if spend < LOW_FACTOR * top:
            out.append(f"kullanım sınırı {_money(spend)} (API karşılığı), bu projede {tier} katmanındaki son {len(costs)} işin en pahalısının "
                       f"({_money(top)}) 1,2 katından az: iş sınıra takılabilir.")
        elif mean > 0 and spend > HIGH_FACTOR * mean:
            out.append(f"kullanım sınırı {_money(spend)} (API karşılığı), bu projede {tier} katmanındaki işlerin ortalamasının ({_money(mean)}) "
                       f"{round(spend / mean)} katı: kullanım sınırı bu işi korumaz. Katmanın varsayılanını kullan.")
    if check:  # P5 (a kod job's certain case was refused before)
        text = kontrol_uyarisi(check)
        if text:
            out.append(text)
    if call_limit is not None:  # P6
        usual = launch.default_max_calls(cfg, tier)
        if usual and call_limit > CALL_FACTOR * usual:
            out.append(f"çağrı sınırı {call_limit}, {tier} katmanının olağan sınırının ({usual}) iki katından fazla: "
                       "iş bu kadar uzun sürecekse daha üst bir katman seç.")
        calls = [(_float(r["Maliyet ($)"]), _float(r.get("Çağrı"))) for r in same]
        calls = [(c, n) for c, n in calls if n]
        if spend is not None and len(calls) >= MIN_EVIDENCE:
            per_call = sum(c for c, _ in calls) / sum(n for _, n in calls)
            reach = int(spend / per_call) if per_call > 0 else None
            if reach is not None and call_limit > reach:
                out.append(f"çağrı sınırı {call_limit} bu kullanım sınırıyla ulaşılamaz: sınır ({_money(spend)}) bu katmandaki "
                           f"ortalama çağrı kullanımıyla (~{_money(per_call)}) yaklaşık {reach} çağrıda dolar.")
    return out


def akis_uyarilari(project, shares, rows):
    """P7: each review share below the most expensive Claude review observed in this project."""
    reviews = [_float(r.get("Maliyet ($)")) for r in rows
               if r.get("Proje") == project and r.get("Katman") == "inceleme" and r.get("Model") not in NOT_CLAUDE]
    reviews = [c for c in reviews if c is not None]
    if not reviews:
        return []
    top = max(reviews)
    out = []
    for kind in REVIEW_KINDS:
        share = _float((shares or {}).get(kind))
        if share is not None and share < top:
            out.append(f"{kind} payı {_money(share)}, bu projede bir Claude incelemesinin gözlenen kullanımının "
                       f"({_money(top)}) altında: Codex karar vermezse Claude incelemesi kullanım sınırına takılabilir. "
                       "--butce'yi artır.")
    return out
