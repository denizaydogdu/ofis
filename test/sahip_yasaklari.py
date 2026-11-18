"""The tests' office configuration (plan "2. Aşama"): a neutral owner with privacy rules of the same shape as a real
owner's, so the tests that exercise the forbidden project, the vault's private folders, the credential words and the
owner's display name run with the same values on every machine — never with the values of the ofis.json of the machine
they run on. Importing this module is enough (test/fakes.py does).

It writes one config file into the system temp directory — ofis.example.json with SAHIP_ADI and SAHIP below — and
points the test-only override at it (bin/yasaklar.py ofis_json: OFIS_TEST=1 and OFIS_CONFIG). Every reader of the
office's configuration (bin/yasaklar.py, bin/sahip.py, bin/guard.py's vault roots, launch.load's default) and every
child process (the guard hook, bin/ofis.py, the server) then reads that file instead of this repository's ofis.json.
A test of other rules points bin/yasaklar.py CONFIG (or bin/sahip.py CONFIG) at a file of its own.

The display name is also set as SAHIP_ENV (bin/sahip.py ENV): it fills in the name wherever a test's own cfg has no
`sahip_adi`, and the JavaScript under node reads it (web/ofis-davranis.js). A test of the default name removes it for
its own duration.

The values (neutral, never a real person's):
- SAHIP_ADI "Selin" takes the same Turkish endings as the earlier owner name (Selin'e, Selin'in, Selin'den);
- yasak_yollar: one lowercase three-letter word with an i (its upper case "ZİM" checks the dotted-İ folding);
- ozel_klasorler: three folders written as a real owner might (mixed case, upper case, upper case with a dotted İ);
- yasak_kelimeler: the generic credential words.
"""
import atexit
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "..", "ofis.example.json")
CONFIG_ENV = "OFIS_CONFIG"  # bin/yasaklar.py TEST_CONFIG_ENV
TEST_ENV = "OFIS_TEST"  # bin/yasaklar.py TEST_ENV
EK_ENV = "OFIS_EK_YASAKLAR"  # bin/yasaklar.py EK_ENV
SAHIP_ENV = "OFIS_SAHIP_ADI"  # bin/sahip.py ENV

YASAK_YOL = "zim"
KLASORLER = ["Mektuplar", "TAPU", "SİGORTA"]
SAHIP = {
    "yasak_yollar": [YASAK_YOL],
    "ozel_klasorler": list(KLASORLER),
    "yasak_kelimeler": ["s" + "ifre", "ş" + "ifre"],
}
SAHIP_ADI = "Selin"


def _yaz():
    with open(EXAMPLE, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["sahip_adi"] = SAHIP_ADI
    cfg["guvenlik"] = SAHIP
    fd, path = tempfile.mkstemp(prefix=f"ofis-test-config-{os.getpid()}-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    atexit.register(lambda: os.path.exists(path) and os.remove(path))
    return path


def kur():
    """A child test process inherits its parent's file (the same values); a new one writes its own."""
    path = os.environ.get(CONFIG_ENV)
    if not (path and os.environ.get(TEST_ENV) == "1" and os.path.isfile(path)):
        os.environ[CONFIG_ENV] = _yaz()
        os.environ[TEST_ENV] = "1"
    os.environ.pop(EK_ENV, None)  # only this file's rules: nothing added from the shell that runs the tests
    os.environ[SAHIP_ENV] = SAHIP_ADI


kur()
