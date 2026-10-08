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
    "approval_policy": "never",
    "sandbox_mode": "workspace-write",
    "web_search": "live",
    "sandbox_workspace_write": {
        "network_access": True,
        "writable_roots": ["$HOME"],
    },
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

        merged = merge_profile(original, PROFILE, Path("/home/operator"))

        self.assertIn('approval_policy = "never"', merged)
        self.assertIn('web_search = "live"', merged)
        self.assertIn('sandbox_mode = "workspace-write"\nweb_search = "live"\n\n[mcp_servers.example]', merged)
        self.assertIn('url = "https://example.invalid/mcp"', merged)
        self.assertIn('[profiles.special]\nsandbox_mode = "read-only"', merged)
        self.assertIn('[sandbox_workspace_write]\nnetwork_access = true\nwritable_roots = ["/home/operator"]', merged)

    def test_update_managed_permission_keys_and_preserve_other_permission_settings(self):
        original = (
            'approval_policy = "on-request"\n'
            '[sandbox_workspace_write]\n'
            'network_access = false\n'
            'exclude_slash_tmp = true\n'
            '[mcp_servers.example]\n'
            'url = "local"\n'
        )

        merged = merge_profile(original, PROFILE, Path("/home/operator"))
        parsed = tomllib.loads(merged)

        self.assertEqual(parsed["sandbox_workspace_write"]["network_access"], True)
        self.assertEqual(parsed["sandbox_workspace_write"]["writable_roots"], ["/home/operator"])
        self.assertEqual(parsed["sandbox_workspace_write"]["exclude_slash_tmp"], True)
        self.assertEqual(parsed["mcp_servers"]["example"]["url"], "local")

    def test_update_dotted_permission_keys_without_adding_duplicate_table(self):
        original = (
            'sandbox_workspace_write.network_access = false\n'
            '[mcp_servers.example]\n'
            'url = "local"\n'
        )

        merged = merge_profile(original, PROFILE, Path("/home/operator"))
        parsed = tomllib.loads(merged)

        self.assertEqual(parsed["sandbox_workspace_write"]["network_access"], True)
        self.assertEqual(parsed["sandbox_workspace_write"]["writable_roots"], ["/home/operator"])
        self.assertNotIn("[sandbox_workspace_write]", merged)

    def test_profile_schema_requires_permissions_and_live_search(self):
        with tempfile.TemporaryDirectory() as directory:
            profile_path = Path(directory) / "profile.json"
            profile_path.write_text('{"model":"x"}')
            from sync_codex_profile import read_profile
            with self.assertRaises(ValueError):
                read_profile(profile_path)

    def test_write_is_idempotent_and_creates_private_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / ".codex" / "config.toml"
            config.parent.mkdir()
            config.write_text('model = "old"\n[mcp_servers.example]\nurl = "local"\n')

            self.assertTrue(apply_profile(config, PROFILE, write=True, home=Path("/home/operator")))
            backups = list(config.parent.glob("config.toml.pre-fleet-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), 'model = "old"\n[mcp_servers.example]\nurl = "local"\n')
            self.assertEqual((config.parent.stat().st_mode & 0o777), 0o700)
            self.assertEqual((config.stat().st_mode & 0o777), 0o600)
            self.assertEqual((backups[0].stat().st_mode & 0o777), 0o600)
            self.assertFalse(apply_profile(config, PROFILE, write=True, home=Path("/home/operator")))

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
