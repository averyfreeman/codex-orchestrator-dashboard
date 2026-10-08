import sys
import tempfile
import unittest
from pathlib import Path
import tomllib

sys.path.insert(0, str(Path(__file__).parent))
from sync_codex_profile import apply_profile, merge_profile


PROFILE = {
    "model": "gpt-6-luna",
    "model_reasoning_effort": "max",
    "approval_policy": "on-request",
    "sandbox_mode": "workspace-write",
}


class CodexProfileSyncTests(unittest.TestCase):
    def test_merge_updates_root_keys_and_preserves_mcp_configuration(self):
        original = (
            'model = "gpt-6-luna"\n'
            'model_reasoning_effort = "max"\n'
            '[mcp_servers.example]\n'
            'url = "https://example.invalid/mcp"\n'
            '[profiles.special]\n'
            'sandbox_mode = "read-only"\n'
        )

        merged = merge_profile(original, PROFILE)

        self.assertIn('approval_policy = "on-request"', merged)
        self.assertIn('sandbox_mode = "workspace-write"\n\n[mcp_servers.example]', merged)
        self.assertIn('url = "https://example.invalid/mcp"', merged)
        self.assertIn('[profiles.special]\nsandbox_mode = "read-only"', merged)

    def test_write_is_idempotent_and_creates_private_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / ".codex" / "config.toml"
            config.parent.mkdir()
            config.write_text('model = "old"\n[mcp_servers.example]\nurl = "local"\n')

            self.assertTrue(apply_profile(config, PROFILE, write=True))
            backups = list(config.parent.glob("config.toml.pre-fleet-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), 'model = "old"\n[mcp_servers.example]\nurl = "local"\n')
            self.assertFalse(apply_profile(config, PROFILE, write=True))

    def test_invalid_toml_is_refused_without_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            original = 'model = "broken\n'
            config.write_text(original)
            with self.assertRaises(tomllib.TOMLDecodeError):
                apply_profile(config, PROFILE, write=True)
            self.assertEqual(config.read_text(), original)


if __name__ == "__main__":
    unittest.main()
