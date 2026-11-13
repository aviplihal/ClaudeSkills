# Tests for the hd module named in the file name (stdlib unittest only).
import json, os, stat, sys, tempfile, threading, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from hd import util


class TestUtil(unittest.TestCase):
    """Tests for hd.util."""

    def tearDown(self):
        """Restore the real clock."""
        util.set_clock(None)

    def test_now_format_and_override(self):
        """now() is ISO Z and set_clock overrides it."""
        self.assertRegex(util.now(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        util.set_clock(lambda: "2020-01-01T00:00:00Z")
        self.assertEqual(util.now(), "2020-01-01T00:00:00Z")

    def test_sha256(self):
        """sha256_hex accepts str and bytes identically."""
        self.assertEqual(util.sha256_hex("abc"), util.sha256_hex(b"abc"))
        self.assertEqual(len(util.sha256_hex("")), 64)

    def test_os_user(self):
        """os_user returns a non-empty string."""
        self.assertTrue(util.os_user())

    def test_modes(self):
        """secure_write makes 0600 files in 0700 dirs, including new parents."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a", "b", "f.txt")
            util.secure_write(p, "hi")
            self.assertEqual(open(p).read(), "hi")
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(p)).st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(d, "a")).st_mode), 0o700)
            util.secure_write(p, "again")
            self.assertEqual(open(p).read(), "again")

    def test_sync_positive(self):
        """Known sync folders are detected, case-insensitively and by prefix."""
        for path, name in [("/Users/x/Nextcloud/logs", "Nextcloud"), ("/home/x/DROPBOX/a", "Dropbox"),
                           ("/Users/x/OneDrive - Corp/a", "OneDrive"),
                           ("/Users/x/Library/Mobile Documents/com~apple~CloudDocs/a", "iCloud Drive (Mobile Documents)"),
                           ("/Users/x/Library/CloudStorage/GoogleDrive-a/b", "CloudStorage"),
                           ("/Users/x/Google Drive/a", "Google Drive"),
                           ("/home/x/syncthing/a", "Syncthing")]:
            self.assertEqual(util.in_sync_folder(path), name, path)

    def test_sync_negative(self):
        """Ordinary paths are not flagged."""
        for path in ["/home/x/.harness-dashboard/car", "/tmp/x", "/Users/x/Documents/drop", "/var/log/hd"]:
            self.assertIsNone(util.in_sync_folder(path), path)


if __name__ == "__main__":
    unittest.main()
