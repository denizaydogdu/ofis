"""Tests for the server's error and event record in the vault (bin/olaylar.py): OFIS/Sunucu/Hatalar-YYYY-MM.md in a
temp vault; deduplication, the line filter, masking, atomic plain-file writes, an unreachable vault."""
import io
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import fakes  # noqa: E402,F401  (isolates the job lock)
import olaylar  # noqa: E402


FAKE_GHP = "gh" + "p_" + "ABCDEFGHIJKLMNOPQRSTUV"  # fake, built at run time (no token-shaped literal for scanners)
FAKE_AKIA = "AK" + "IA" + "ABCDEFGHIJKLMNOP"  # fake

class Clock:
    def __init__(self, when=datetime(2026, 11, 11, 9, 30)):
        self.when = when
        self.mono = 1000.0

    def now(self):
        return self.when

    def clock(self):
        return self.mono


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = self.tmp.name
        self.t = Clock()
        self.local = io.StringIO()
        self.ev = olaylar.Olaylar(self.vault, now=self.t.now, clock=self.t.clock, local=self.local)
        self.path = os.path.join(self.vault, "Sunucu", "Hatalar-2026-11.md")

    def read(self):
        with open(self.path, encoding="utf-8") as f:
            return f.read()

    def rows(self):
        return [line for line in self.read().splitlines() if olaylar.ROW.match(line)]

    def test_quoted_credentials_are_masked_in_json_and_python_dict_styles(self):
        for text, secret in (('{"token": "abc123"}', "abc123"), ("{'password': 'hunter2'}", "hunter2"),
                             ('{"api_key":"k-9876543"}', "k-9876543"), ("Authorization: Bearer xyz.987", "xyz.987"),
                             ("token=plain1", "plain1"), ("secret: s3cr3t", "s3cr3t"),
                             ('"Authorization": "Bearer qq77"', "qq77")):
            with self.subTest(text=text):
                self.assertNotIn(secret, olaylar.clean(text))
        self.assertIn("token", olaylar.clean('{"token": "abc123"}'))  # the key stays readable

    def test_unquoted_values_are_masked_to_the_next_space_and_escaped_quotes_never_leak(self):
        for text, leak in (("password=abc,def", "def"), ("token=a;b", "b"), ("api_key=x&y=z", "y=z"),
                           ('"password": "ab\\"cd\\"ef"', "ef"), ('"password": "ab\\"cd\\"ef"', "cd"),
                           ("'secret': 'it\\'s-x9'", "s-x9"), ('{"token": "unterminated rest', "rest")):
            with self.subTest(text=text):
                self.assertNotIn(leak, olaylar.clean(text).replace("***", ""))
        out = olaylar.clean("ilk satır\npassword=x1 sonra\nson satır")
        self.assertEqual(out, "ilk satır password=*** sonra son satır")  # only the secret is masked

    def test_an_undecodable_month_file_is_never_overwritten_and_never_raises(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "wb") as f:
            f.write(b"| 2026-11-01 10:00 | 2026-11-01 10:00 | 1 | hata | \xff\xfe bozuk |\n")
        before = open(self.path, "rb").read()
        self.ev.record("hata", "inbox x: OSError")  # must not raise
        self.assertEqual(open(self.path, "rb").read(), before)

    def test_the_log_stream_never_raises_because_of_the_record(self):
        class Boom:
            def record(self, kind, text):
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")
        inner = io.StringIO()
        tee = olaylar._Tee(Boom(), inner)
        tee.write("ofis: inbox x: OSError\n")
        self.assertEqual(inner.getvalue(), "ofis: inbox x: OSError\n")

    def test_home_folders_are_masked_at_the_source(self):
        self.assertEqual(olaylar.clean("cannot read /Users/deniz/Documents/Vault/OFIS: x"),
                         "cannot read ~/Documents/Vault/OFIS: x")
        self.assertEqual(olaylar.clean("/home/u/a b"), "~/a b")

    def test_the_newest_rows_for_the_page_without_the_start_event(self):
        from datetime import timedelta
        self.assertEqual(self.ev.son(), [])
        self.ev.record("başlangıç", "sunucu başladı (pid 1, port 8800)")
        self.ev.record("hata", "inbox x: OSError")
        self.t.when += timedelta(minutes=5)
        self.ev.record("teslim", "delivery unconfirmed")
        self.ev.record("hata", "inbox x: OSError")
        out = self.ev.son(5)
        self.assertEqual([(r["tur"], r["sayi"]) for r in out], [("hata", 2), ("teslim", 1)])
        self.assertEqual(set(out[0]), {"tur", "ileti", "sayi", "son"})
        self.assertEqual(len(self.ev.son(1)), 1)

    def test_a_new_kind_is_written_at_once_with_the_header(self):
        self.ev.record("başlangıç", "sunucu başladı (pid 4242, port 8800)")
        text = self.read()
        self.assertTrue(text.startswith("---\ntags: [ofis, sunucu]\n"))
        self.assertIn(olaylar.INTRO, text)
        self.assertIn("| İlk görülme | Son görülme | Sayı | Tür | İleti |", text)
        self.assertEqual(self.rows(), ["| 2026-11-11 09:30 | 2026-11-11 09:30 | 1 | başlangıç | "
                                       "sunucu başladı (pid 4242, port 8800) |"])

    def test_a_repeat_updates_the_row_in_place_at_the_next_flush(self):
        self.ev.record("hata", "ofis dispatcher: start of 2026-11-10-183820-blog failed: OSError: x")
        self.t.when = datetime(2026, 11, 11, 10, 5)
        self.ev.record("hata", "ofis dispatcher: start of 2026-11-11-090000-blog failed: OSError: x")
        self.assertIn("| 1 |", self.rows()[0])  # not yet: at most every 30 s
        self.assertFalse(self.ev.flush())
        self.t.mono += 31
        self.assertTrue(self.ev.flush())
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].startswith("| 2026-11-11 09:30 | 2026-11-11 10:05 | 2 | hata | "), rows[0])
        self.assertIn("2026-11-11-090000-blog", rows[0])  # the latest text is shown

    def test_counts_go_on_after_a_restart_and_a_new_month_is_a_new_file(self):
        self.ev.record("başlangıç", "sunucu başladı (pid 1, port 8800)")
        again = olaylar.Olaylar(self.vault, now=self.t.now, clock=self.t.clock, local=self.local)
        again.record("başlangıç", "sunucu başladı (pid 2, port 8801)")
        again.flush(force=True)
        self.assertIn("| 2 | başlangıç |", self.rows()[0])
        self.t.when = datetime(2026, 12, 1, 0, 1)
        again.record("başlangıç", "sunucu başladı (pid 3, port 8800)")
        with open(os.path.join(self.vault, "Sunucu", "Hatalar-2026-12.md"), encoding="utf-8") as f:
            self.assertIn("| 1 | başlangıç |", f.read())

    def test_text_is_one_capped_plain_line_with_temp_paths_and_credentials_masked(self):
        long = "RuntimeError: " + "a" * 400
        self.ev.record("hata", "ofis kontrol: x | y\nz /private/var/folders/ab/T/tmpq1/x.json token=abc123 " + long)
        row = self.rows()[0]
        msg = row.split(" | ")[-1].rstrip(" |")
        self.assertLessEqual(len(msg), olaylar.MAX_TEXT)
        self.assertNotIn("abc123", row)
        self.assertIn("token=***", row)
        self.assertIn("‹geçici›", row)  # no raw < > in the note
        self.assertNotIn("tmpq1", row)
        self.assertEqual(row.count("|"), 6)

    def test_only_error_lines_of_the_log_stream_are_kept(self):
        inner = io.StringIO()
        s = self.ev.stream(inner)
        s.write("ofis post office: answer delivered to ofis-blog\n")
        s.write("ofis dispatcher: started 2026-11-11-0900-blog\n")
        s.write("ofis kontrol: kontrol of x failed (attempt 1); sent back to y\n")  # a job's Kontrol: not a server error
        s.write("ofis post office: rejected 123.json: invalid session name\n")
        s.write("ofis post office: outbox 1-cevap-x.json: session gone\n")
        s.write("ofis post office: dispatcher: KeyError: 'proje'")
        s.write("\n")
        self.assertIn("answer delivered", inner.getvalue())  # everything still reaches the local log
        kinds = sorted(r.split(" | ")[3] for r in self.rows())
        self.assertEqual(kinds, ["giden", "hata", "reddedildi"])

    def test_sources_are_recorded_when_their_value_changes(self):
        box = {"v": None, "d": {}}
        self.ev.watch("ceo", "teslim", lambda: box["v"])
        self.ev.watch("projeler", "teslim", lambda: dict(box["d"]))
        self.ev.watch("bozuk", "teslim", lambda: 1 / 0)
        self.ev.poll()
        self.assertFalse(os.path.exists(self.path))
        box["v"] = "delivery unconfirmed (timeout); not re-sent"
        box["d"] = {"ofis-blog": "claude timed out before the message was sent"}
        self.ev.poll()
        self.ev.poll()  # unchanged: not counted again
        box["v"] = None
        self.ev.poll()
        box["v"] = "delivery unconfirmed (timeout); not re-sent"
        self.ev.poll()
        self.ev.flush(force=True)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertTrue(any("| 2 | teslim | delivery unconfirmed" in r for r in rows), rows)
        self.assertTrue(any("ofis-blog: claude timed out" in r for r in rows), rows)

    def test_an_unconfirmed_launch_keeps_its_masked_output_tail_in_the_record(self):
        # 2026-11-13 (claude 2.1.323): the launch line changed and its output was lost; the log line of the channel
        # carries a ≤ 300-character tail, so the delivery kind keeps a longer text than other kinds
        tail = "stdout: " + "x" * 260 + " NEW-FORMAT-END"
        s = self.ev.stream(io.StringIO())
        s.write("ofis post office: ofis-arge-1113-095913-67e7: launch unconfirmed: claude resumed the "
                f"ofis-arge-1113-095913-67e7 session without the expected launch line; output: {tail} token=abc9\n")
        [row] = self.rows()
        self.assertEqual(row.split(" | ")[3], "teslim")
        self.assertIn("NEW-FORMAT-END", row, "the end of the tail is kept")
        self.assertNotIn("abc9", row)
        self.assertLessEqual(len(row.split(" | ")[-1]), olaylar.KIND_LIMITS["teslim"] + 2)
        self.ev.record("hata", "RuntimeError: " + "a" * 400)
        hata = next(r for r in self.rows() if " | hata | " in r)
        self.assertLessEqual(len(hata.split(" | ")[-1].rstrip(" |")), olaylar.MAX_TEXT, "other kinds keep 200")

    def test_compound_keys_and_known_token_shapes_are_masked(self):
        # review MAJOR 2026-11-13: the output tail of an unknown claude launch is untrusted text going to the vault
        text = ("access_token=abc123 refresh_token: xyz9 client_secret=s3c ANTHROPIC_API_KEY=foo123 x-api-key: k1q "
                "Cookie: sid=zz77 credentials=cr3d " + FAKE_GHP + " " + "github" + "_pat_" + "11ABCDEFGHIJKLMNOPQR_x "
                "" + "xo" + "xb-1234567890-abcdef " + FAKE_AKIA + " eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.sig123")
        out = olaylar.maskele(text)
        for leak in ("abc123", "xyz9", "s3c", "foo123", "k1q", "zz77", "cr3d", "ABCDEFGHIJKLMNOPQRSTUV",
                     "11ABCDEFGHIJKLMNOPQR", "1234567890-abcdef", FAKE_AKIA, "eyJzdWIiOiIxMjM0"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, out)
        self.assertIn("access_token=***", out, "the key stays readable")
        self.assertEqual(olaylar.maskele("outbox 1-cevap-x.json: session gone"), "outbox 1-cevap-x.json: session gone")

    def test_maskele_masks_without_capping_or_rewriting(self):
        text = "a" * 300 + " token=abc1 Bearer q.w sk-ant-0123456789ab /Users/deniz/x [x] <y>"
        out = olaylar.maskele(text)
        self.assertTrue(out.startswith("a" * 300))
        for leak in ("abc1", "q.w", "0123456789ab", "deniz"):
            self.assertNotIn(leak, out)
        self.assertIn("[x] <y>", out, "only masking: the note-specific escaping is clean()'s job")

    def test_a_symlinked_folder_or_file_is_refused_and_the_server_goes_on(self):
        elsewhere = os.path.join(self.vault, "elsewhere")
        os.makedirs(elsewhere)
        os.symlink(elsewhere, os.path.join(self.vault, "Sunucu"))
        self.ev.record("hata", "x failed")
        self.ev.record("hata", "y failed")
        self.assertEqual(os.listdir(elsewhere), [])
        self.assertEqual(self.local.getvalue().count("yazılamadı"), 1)  # said once

    def test_a_symlinked_month_file_is_refused(self):
        os.makedirs(os.path.join(self.vault, "Sunucu"))
        target = os.path.join(self.vault, "target.md")
        with open(target, "w") as f:
            f.write("keep\n")
        os.symlink(target, self.path)
        self.ev.record("hata", "x failed")
        with open(target) as f:
            self.assertEqual(f.read(), "keep\n")

    def test_an_unreachable_vault_is_no_error(self):
        ev = olaylar.Olaylar(os.path.join(self.vault, "yok"), now=self.t.now, clock=self.t.clock, local=self.local)
        ev.record("obsidian", "ofis: HATA Obsidian notlarına erişilemiyor")
        self.assertFalse(os.path.exists(os.path.join(self.vault, "yok")))
        self.assertIn("yazılamadı", self.local.getvalue())

    def test_a_month_file_that_could_not_be_read_is_never_overwritten_and_its_rows_are_kept(self):
        os.makedirs(os.path.join(self.vault, "Sunucu"))
        earlier = olaylar.Olaylar(self.vault, now=self.t.now, clock=self.t.clock, local=self.local)
        for _ in range(5):
            earlier.record("başlangıç", "sunucu başladı (pid 1, port 8800)")
        earlier.flush(force=True)
        before = self.read()
        os.chmod(self.path, 0)  # e.g. macOS refuses the vault when the server starts
        try:
            self.ev.record("hata", "x failed")
            self.ev.record("başlangıç", "sunucu başladı (pid 2, port 8801)")
            self.t.mono += 31
            self.ev.flush()
        finally:
            os.chmod(self.path, 0o644)
        self.assertEqual(self.read(), before, "a month file that was not read is not replaced")
        self.t.mono += 31
        self.assertTrue(self.ev.flush())  # readable again: read, merged, written
        rows = {r.split(" | ")[3]: r for r in self.rows()}
        self.assertIn("| 6 | başlangıç |", rows["başlangıç"])  # 5 earlier + 1 while unreadable
        self.assertIn("| 1 | hata | x failed |", rows["hata"])
        self.ev.record("hata", "x failed")
        self.ev.flush(force=True)
        self.assertIn("| 2 | hata |", {r.split(" | ")[3]: r for r in self.rows()}["hata"])  # merged once only

    def test_project_controlled_text_is_not_stored(self):
        s = self.ev.stream(io.StringIO())
        s.write("ofis post office: rejected [[Kotu]]-1.json: invalid type\n")
        s.write("ofis post office: rejected 2.json: sent from /Users/x/[[Sahte]]/y, outside the job's working "
                "folder /Users/x/blog\n")
        s.write("ofis kontrol: cannot run: RuntimeError: Authorization: Bearer abc.def.ghi key sk-ant-api03-SECRETxyz12\n")
        text = self.read()
        for bad in ("[[", "]]", "Kotu", "Sahte", "/Users/x", "abc.def.ghi", "SECRETxyz12"):
            self.assertNotIn(bad, text)
        self.assertIn("rejected (dosya): invalid type", text)
        self.assertIn("sent from (klasör), outside the job's working folder", text)
        self.assertIn("Bearer ***", text)
        self.assertIn("sk-***", text)

    def test_the_run_loop_flushes_on_stop(self):
        self.ev.record("hata", "x failed")
        self.ev.record("hata", "x failed")
        stop = threading.Event()
        stop.set()
        self.ev.run(stop, interval=0.01)
        self.assertIn("| 2 | hata |", self.rows()[0])


if __name__ == "__main__":
    unittest.main()
