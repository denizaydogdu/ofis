"""The slow-test mark: `@yavas` skips a test (or a TestCase class) in the fast run (`python3 test/hepsi.py --hizli`, which
sets OFIS_HIZLI=1). OFIS_YAVAS=1 includes the slow tests even then. Every other run (the default full run, a file run on
its own) includes them."""
import os
import unittest


def hizli():
    return os.environ.get("OFIS_HIZLI") == "1" and os.environ.get("OFIS_YAVAS") != "1"


def yavas(obj):
    return unittest.skipIf(hizli(), "slow test (hızlı mod; OFIS_YAVAS=1 includes it)")(obj)
