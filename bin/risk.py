"""Risk-based review (riske göre inceleme): a pure classifier of a kod step's change, used by the review panel
(bin/akis.py DenetciHeyeti) and the approval card. Deterministic code, no model call, no I/O.

risk_seviyesi(changed_paths, diff_stats, proje_cfg) -> (level, reasons):
- "yuksek" when a changed path is sensitive (SENSITIVE: authentication / sessions / tokens / password reset /
  permissions; payment / billing / subscriptions / purchases; CI and deployment files; database migrations and schemas;
  installer / updater / release configuration; secrets and key files; agent and tool configuration — CLAUDE.md,
  AGENTS.md, .claude/, .mcp.json, .vscode/tasks.json, .envrc, git hooks; app permissions — Info.plist, entitlements,
  AndroidManifest.xml; dependency manifests) or matches the project's
  own globs (ofis.json `projects.<P>.hassas_yollar`, fnmatch, matched against the repository-relative path and its
  file name). Lockfiles alone are never yüksek (at least normal): a lockfile change follows a manifest change, which is.
  The name-based reasons (authentication, payment) look at a documentation or test file's folders only, at every
  other file's whole path.
- "dusuk" when every changed path is documentation or a test — recognised by the file name only (DOC_NAME; TEST_NAME
  case-sensitive on the original name), never by a docs/ or spec/ folder — and the change is small (at most
  LOW_MAX_LINES changed lines; a path without a line count — a binary or unreadable file — is never düşük).
- "normal" otherwise (also an empty or unreadable change: the panel then runs as before).
The reasons are short Turkish lines for the approval card and the record; every path in them is escaped (shown_path:
control, line-separator and bidi characters as \\uXXXX), so a file name can never start a card line or section.
The level never lowers the Kontrol or the approval card: düşük only trims the reviewer panel, yüksek adds the
security reviewer.
"""
import fnmatch
import re

LEVELS = ("dusuk", "normal", "yuksek")
LABEL = {"dusuk": "düşük", "normal": "normal", "yuksek": "yüksek"}
LOW_MAX_LINES = 40
MAX_PROJECT_GLOBS = 50
MAX_GLOB = 200
SHOW = 3  # paths named per reason

# (reason, pattern on the lower-cased repository-relative path with "/" separators)
SENSITIVE = (
    ("kimlik doğrulama / oturum / yetki",
     r"(auth(?!or)|login|logout|sign[_-]?in|sign[_-]?up|session|token|passw|parola|sifre|şifre|credential"
     r"|permission|yetki|rbac|security|guvenlik|güvenlik|(?<![a-z])(jwt|saml|sso|2fa|mfa|otp|acl)(?![a-z]))"),
    ("ödeme / abonelik / satın alma",
     r"(payment|billing|subscription|purchase|checkout|invoice|odeme|ödeme|fatura|abonelik|storekit|revenuecat"
     r"|stripe|paypal|iyzico|(?<![a-z])in[_-]?app(?![a-z]))"),
    ("CI / iş akışı / dağıtım",
     r"(^|/)(\.github/workflows/|\.github/actions/|\.gitlab-ci|\.circleci/|fastlane/|jenkinsfile|azure-pipelines|bitbucket-pipelines"
     r"|codemagic\.ya?ml|\.travis\.yml|dockerfile|docker-compose|k8s/|kubernetes/|helm/|terraform/|[^/]*\.tf$)"),
    ("veritabanı geçişi / şema",
     r"((^|/)migrations?/|\.sql$|liquibase|flyway|(^|/)db/changelog|schema\.prisma|(^|/)prisma/|drizzle|alembic"
     r"|(^|/)schema\.rb$)"),
    ("kurulum / otomatik güncelleme / sürüm",
     r"(installer|(^|/)install\.[a-z]+$|(^|/)setup\.(py|sh)$|updater|auto[_-]?update|sparkle|appcast"
     r"|(^|/)\.releaserc|(^|/)release\.(ya?ml|json|toml|sh)$|release-please|goreleaser|launchagent|launchdaemon)"),
    ("gizli bilgi / anahtar",
     r"((^|/)\.env($|\.)|secret|credentials|\.pem$|\.key$|\.p12$|\.p8$|\.keystore$|\.jks$|google-services\.json$"
     r"|googleservice-info\.plist$|(^|/)key\.properties$|\.netrc$)"),
    ("ajan / araç yapılandırması",
     r"((^|/)(claude|agents|gemini)\.md$|(^|/)\.claude/|(^|/)\.mcp\.json$|(^|/)\.cursor/|(^|/)\.cursorrules$"
     r"|(^|/)\.vscode/tasks\.json$|(^|/)\.github/copilot-instructions\.md$|(^|/)\.github/(instructions|prompts)/"
     r"|(^|/)\.clinerules(/|$)|(^|/)\.windsurf/rules/|(^|/)\.windsurfrules$|(^|/)\.roo/rules|(^|/)\.junie/"
     r"|(^|/)\.envrc$|(^|/)\.git/|(^|/)\.githooks/|(^|/)\.husky/|(^|/)\.pre-commit-config\.ya?ml$"
     r"|(^|/)\.gitattributes$|(^|/)\.gitignore$|(^|/)\.gitmodules$)"),
    ("test altyapısı (Kontrol'ün kanıtladığını değiştirebilir)",
     r"((^|/)conftest\.py$|(^|/)pytest\.ini$|(^|/)tox\.ini$|(^|/)\.coveragerc$|(^|/)(jest|vitest|karma|playwright"
     r"|cypress)\.config\.[a-z]+$|(^|/)\.mocharc|(^|/)phpunit\.xml|(^|/)dart_test\.yaml$|(^|/)analysis_options\.yaml$)"),
    ("uygulama izinleri / platform yapılandırması",
     r"((^|/)info\.plist$|\.entitlements$|(^|/)androidmanifest\.xml$|(^|/)network_security_config\.xml$)"),
    ("bağımlılık bildirimi",
     r"(^|/)(package\.json|pubspec\.yaml|build\.gradle(\.kts)?|settings\.gradle(\.kts)?|podfile|gemfile"
     r"|[^/]*requirements[^/]*\.(txt|in)|requirements/[^/]+|constraints[^/]*\.txt|pyproject\.toml|setup\.cfg|pipfile"
     r"|go\.mod|cargo\.toml|pom\.xml|composer\.json|package\.swift|[^/]*\.podspec|cmakelists\.txt|[^/]*\.cmake"
     r"|makefile|gnumakefile|meson\.build|build\.xml)$"),
)
SENSITIVE_RE = tuple((reason, re.compile(pattern)) for reason, pattern in SENSITIVE)
KEYWORD_REASONS = (SENSITIVE[0][0], SENSITIVE[1][0])  # name-based: for a doc or test file only its folders count
LOCKFILE = re.compile(r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|pubspec\.lock|podfile\.lock|gemfile\.lock"
                      r"|poetry\.lock|pipfile\.lock|cargo\.lock|go\.sum|composer\.lock|gradle\.lockfile"
                      r"|package\.resolved)$")
# documentation and tests are recognised by the FILE NAME only (a docs/ or spec/ folder alone proves nothing)
# .txt only for the usual documentation names (CMakeLists.txt, requirements*.txt, constraints.txt are build input)
DOC_NAME = re.compile(r"(\.(md|markdown|rst|adoc)|^(readme|license|licence|changelog|changes|history|authors|notice"
                      r"|contributing|contributors|copying|todo|robots|humans|security|code_of_conduct)(\.[a-z]+)?)$",
                      re.I)
# matched on the ORIGINAL file name, case-sensitive: LoginTests.swift is a test, AppAttest.swift / latest.java not
TEST_NAME = re.compile(r"^(test_[^/]+\.py|[^/]+_test\.[A-Za-z]+|[^/]+\.(test|spec)\.[A-Za-z]+"
                       r"|[^/]*[a-z0-9](Test|Tests|Spec)\.(swift|kt|java|m|mm))$")
# control, line-separator and bidi characters, and \ufffd (an undecodable byte): never written raw into a card line
UNSAFE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u200e\u200f\u202a-\u202e\u2066-\u2069\ufffd]")


def shown_path(path):
    """A path for a card or report line: control, line-separator and bidi characters escaped (a file name can never
    start a line, a note section or a finding), in backticks unless it holds one."""
    text = UNSAFE.sub(lambda m: f"\\u{ord(m.group()):04x}", str(path))
    return text if "`" in text else f"`{text}`"


def one_line(text):
    """A reason read back from a record: one line, every unsafe character escaped."""
    return UNSAFE.sub(lambda m: f"\\u{ord(m.group()):04x}", str(text or ""))


def project_globs(proje_cfg):
    """The valid `hassas_yollar` globs of a project's ofis.json entry (strings, at most MAX_PROJECT_GLOBS)."""
    raw = (proje_cfg or {}).get("hassas_yollar") if isinstance(proje_cfg, dict) else None
    if not isinstance(raw, list):
        return []
    return [g.strip() for g in raw if isinstance(g, str) and g.strip() and len(g) <= MAX_GLOB][:MAX_PROJECT_GLOBS]


def _norm(path):
    out = str(path or "").replace("\\", "/")
    while out.startswith("./"):
        out = out[2:]
    return out.lstrip("/")


def _matches_glob(path, glob):
    name = path.rsplit("/", 1)[-1]
    g = _norm(glob).lower()
    return fnmatch.fnmatchcase(path, g) or fnmatch.fnmatchcase(name, g) or \
        (g.endswith("/") and (path.startswith(g) or f"/{g}" in f"/{path}")) or \
        (g.endswith("/**") and (path.startswith(g[:-2]) or f"/{g[:-2]}" in f"/{path}"))


def kind(path):
    """"belge", "test" or "" for a repository-relative path (by its file name)."""
    name = _norm(path).rsplit("/", 1)[-1]
    if TEST_NAME.match(name):
        return "test"
    if DOC_NAME.search(name):
        return "belge"
    return ""


def _short(paths):
    shown = ", ".join(shown_path(p) for p in paths[:SHOW])
    return shown + (f" (+{len(paths) - SHOW})" if len(paths) > SHOW else "")


def risk_seviyesi(changed_paths, diff_stats=None, proje_cfg=None):
    """(level, reasons) of a change: see the module doc. changed_paths: repository-relative paths (tracked changes and
    untracked new files), None when they could not be read. diff_stats: {path: changed line count or None}."""
    if changed_paths is None:
        return "normal", ["değişiklik listesi okunamadı; inceleme her zamanki gibi"]
    paths = [p for p in dict.fromkeys(str(p) for p in changed_paths if p)]
    if not paths:
        return "normal", ["değişen dosya bulunamadı; inceleme her zamanki gibi"]
    stats = diff_stats if isinstance(diff_stats, dict) else {}
    hits = {}
    for path in paths:
        low = _norm(path).lower()
        folder = low.rsplit("/", 1)[0] + "/" if "/" in low else ""
        light = bool(kind(path))
        for reason, pattern in SENSITIVE_RE:
            # a doc or test file never raises a name-based reason by its own name, always by its folders
            target = folder if light and reason in KEYWORD_REASONS else low
            if target and pattern.search(target):
                hits.setdefault(reason, []).append(path)
        for glob in project_globs(proje_cfg):
            if _matches_glob(low, glob):
                hits.setdefault("projenin hassas yolu (hassas_yollar)", []).append(path)
                break
    if hits:
        return "yuksek", [f"{reason}: {_short(found)}" for reason, found in hits.items()]
    counts = [stats.get(p) for p in paths]
    known = all(isinstance(c, int) and not isinstance(c, bool) and c >= 0 for c in counts)
    lines = sum(counts) if known else None
    locks = [p for p in paths if LOCKFILE.search(_norm(p).lower())]
    kinds = {kind(p) for p in paths}
    if not locks and "" not in kinds and lines is not None and lines <= LOW_MAX_LINES:
        return "dusuk", [f"yalnız {' ve '.join(sorted(kinds))} dosyaları, {len(paths)} dosya, {lines} satır"]
    size = f"{len(paths)} dosya" + (f", {lines} satır" if lines is not None else "")
    reasons = [f"hassas yol yok; {size}"]
    if locks:
        reasons.append(f"kilit dosyası değişti: {_short(locks)}")
    return "normal", reasons


def label(level):
    return LABEL.get(level, level or "—")
