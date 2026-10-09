import base64
import json
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import codex_sync


class CodexSyncFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        self.home = self.root / "user"
        self.codex_home = self.home / ".codex"
        self.home.mkdir()
        self.codex_home.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_discovers_named_profiles_and_only_exposes_classified_config_values(self):
        (self.codex_home / "config.toml").write_text(
            'model = "gpt-6.1-sol"\napi_key = "fixture-secret-that-must-not-escape"\n'
            "[features]\nshell_tool = true\n",
            encoding="utf-8",
        )
        (self.codex_home / "focused.config.toml").write_text('model = "gpt-6-luna"\n', encoding="utf-8")
        (self.codex_home / ".private.config.toml").write_text('model = "hidden"\n', encoding="utf-8")
        (self.codex_home / "nested").mkdir()
        (self.codex_home / "nested" / "ignored.config.toml").write_text('model = "nested"\n', encoding="utf-8")

        state = codex_sync._toml_inventory(self.codex_home, self.home)
        self.assertEqual(state["profileNames"], ["focused.config.toml"])
        config = state["files"][0]
        self.assertEqual(config["portable"], {"model": "gpt-6.1-sol", "features.shell_tool": True})
        self.assertNotIn("fixture-secret-that-must-not-escape", repr(state))
        self.assertEqual(state["files"][1]["portable"]["model"], "gpt-6-luna")

    def test_treats_symlink_and_oversized_config_as_blocked(self):
        outside = self.root / "outside.toml"
        outside.write_text('model = "outside"\n', encoding="utf-8")
        (self.codex_home / "config.toml").symlink_to(outside)
        state = codex_sync._toml_state(self.codex_home / "config.toml", "config.toml", self.home)
        self.assertTrue(state["invalid"])
        self.assertEqual(state["portable"], {})

        oversized = self.codex_home / "large.config.toml"
        oversized.write_bytes(b"#" + b"x" * codex_sync.MAX_FILE_BYTES)
        state = codex_sync._toml_state(oversized, oversized.name, self.home)
        self.assertTrue(state["invalid"])
        self.assertEqual(state["hash"], None)

    def test_rejects_generated_marketplace_caches_and_validates_editable_local_package(self):
        cached = self.codex_home / ".tmp" / "bundled-marketplaces" / "sample"
        cached.mkdir(parents=True)
        cached_state = codex_sync._marketplace_source({"sourceType": "local", "source": str(cached)}, str(cached), self.codex_home)
        self.assertEqual(cached_state["kind"], "unknown")

        source = self.home / "local-marketplace"
        package = source / "packages" / "demo"
        package.mkdir(parents=True)
        (source / "marketplace.json").write_text(json.dumps({
            "name": "fixture-marketplace",
            "plugins": [{"name": "demo", "source": {"source": "local", "path": "./packages/demo"}}],
        }), encoding="utf-8")
        (package / "plugin.json").write_text(json.dumps({"name": "demo"}), encoding="utf-8")
        (package / "README.md").write_text("safe fixture package\n", encoding="utf-8")
        result = codex_sync._find_local_plugin_package({"root": str(source)}, "demo", self.codex_home)
        self.assertTrue(result["ok"])
        self.assertIn("plugin.json", result["files"])
        self.assertNotIn("safe fixture package", repr(result["files"]))

        (package / "secret.env").write_text("fixture", encoding="utf-8")
        result = codex_sync._find_local_plugin_package({"root": str(source)}, "demo", self.codex_home)
        self.assertFalse(result["ok"])

    def test_codex_owned_openai_marketplaces_use_cli_sources_without_copying_caches(self):
        cache = self.codex_home / ".tmp" / "plugins"
        cache.mkdir(parents=True)
        marketplace_payload = {"marketplaces": [{
            "name": "openai-curated",
            "marketplaceSource": {"sourceType": "local", "source": str(cache)},
            "root": str(cache),
        }]}
        plugin_payload = {"installed": [{
            "name": "fixture-plugin",
            "marketplaceName": "openai-curated-remote",
            "enabled": True,
            "version": "1.2.3",
        }]}

        def fake_run(args, **_kwargs):
            payload = marketplace_payload if args[1:4] == ["plugin", "marketplace", "list"] else plugin_payload
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

        with patch.object(codex_sync, "_run", side_effect=fake_run):
            state = codex_sync._read_plugin_cli("codex", {}, self.codex_home, include_package_content=True)

        markets = {market["name"]: market for market in state["marketplaces"]}
        self.assertEqual(markets["openai-curated"]["kind"], "managed")
        self.assertEqual(markets["openai-curated-remote"]["kind"], "managed")
        self.assertEqual(state["plugins"][0]["marketplaceKind"], "managed")
        self.assertNotIn("transferBlocked", state["plugins"][0])
        self.assertEqual(state["localPackages"], {})

    def test_generated_local_marketplace_uses_the_supported_agents_manifest_location(self):
        run_id = "01234567-89ab-cdef-0123-456789abcdef"
        market_root = codex_sync._write_local_marketplace(self.codex_home, {"name": "fixture-market", "kind": "local"}, {
            "demo": {"plugin.json": base64.b64encode(b'{"name":"demo"}').decode()},
        }, run_id)
        catalog = market_root / ".agents" / "plugins" / "marketplace.json"
        self.assertTrue(catalog.is_file())
        self.assertFalse((market_root / "marketplace.json").exists())
        manifest = json.loads(catalog.read_text(encoding="utf-8"))
        self.assertEqual(manifest["plugins"][0]["source"]["path"], "./packages/demo")

    def test_skill_inventory_stays_in_user_roots_and_excludes_system_repo_and_symlink_skills(self):
        agents = self.home / ".agents" / "skills"
        codex_skills = self.codex_home / "skills"
        for skill in (agents / "editor", codex_skills / "review", codex_skills / ".system" / "internal"):
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("fixture skill\n", encoding="utf-8")
        repo_skill = self.root / "repo" / ".agents" / "skills" / "repo-only"
        repo_skill.mkdir(parents=True)
        (repo_skill / "SKILL.md").write_text("repo skill\n", encoding="utf-8")
        external = self.root / "external-skill"
        external.mkdir()
        (external / "SKILL.md").write_text("outside root\n", encoding="utf-8")
        (agents / "linked-skill").symlink_to(external, target_is_directory=True)

        inventory = codex_sync._skill_inventory(self.home, self.codex_home, include_content=False)
        self.assertEqual(set(inventory["skills"]), {"agents/editor", "codex/review"})
        self.assertIn("agents/linked-skill", inventory["blocked"])
        self.assertEqual(inventory["skills"]["agents/editor"]["files"], {})
        self.assertEqual(inventory["skills"]["agents/editor"]["fileNames"], ["SKILL.md"])

    def test_symlinked_user_skill_parent_is_blocked(self):
        external = self.root / "external"
        (external / "skills").mkdir(parents=True)
        linked_home = self.root / "linked-home"
        linked_home.mkdir()
        (linked_home / ".agents").symlink_to(external, target_is_directory=True)

        inventory = codex_sync._skill_inventory(linked_home, self.codex_home, include_content=True)
        self.assertIn("agents/<unsafe-root>", inventory["blocked"])
        with self.assertRaises(codex_sync.SyncError):
            codex_sync._apply_skills(linked_home, self.codex_home, {
                "write": [{"root": "agents", "skill": "new-skill", "path": "SKILL.md", "content": base64.b64encode(b"x").decode()}],
                "delete": [], "deleteFiles": [],
            }, "01234567-89ab-cdef-0123-456789abcdef")

    def test_config_apply_is_idempotent_and_keeps_private_backups(self):
        config = self.codex_home / "config.toml"
        config.write_text('model = "gpt-6-luna"\n[features]\nshell_tool = false\n', encoding="utf-8")
        actions = [{"name": "config.toml", "values": {"model": "gpt-6.1-sol", "features.shell_tool": True}, "remove": []}]
        run_id = "01234567-89ab-cdef-0123-456789abcdef"

        first = codex_sync._apply_configs(self.codex_home, actions, run_id)
        self.assertEqual(first["filesChanged"], 1)
        parsed = codex_sync.tomllib.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(parsed["model"], "gpt-6.1-sol")
        self.assertTrue(parsed["features"]["shell_tool"])
        second = codex_sync._apply_configs(self.codex_home, actions, run_id)
        self.assertEqual(second["filesChanged"], 0)
        backup = self.codex_home / "fleet-sync-backups" / run_id / "config" / f"config.toml.{run_id}.bak"
        self.assertTrue(backup.is_file())
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)

    def test_config_apply_rolls_back_all_files_if_a_later_profile_write_fails(self):
        config = self.codex_home / "config.toml"
        profile = self.codex_home / "focused.config.toml"
        config.write_text('model = "before"\n', encoding="utf-8")
        profile.write_text('model = "before-profile"\n', encoding="utf-8")
        actions = [
            {"name": "config.toml", "values": {"model": "after"}, "remove": []},
            {"name": "focused.config.toml", "values": {"model": "after-profile"}, "remove": []},
        ]
        original_write = codex_sync._atomic_write
        fail_once = {"pending": True}

        def fail_profile_once(path, data, mode=0o600):
            if path == profile and fail_once["pending"]:
                fail_once["pending"] = False
                raise OSError("fixture failure")
            return original_write(path, data, mode)

        with patch.object(codex_sync, "_atomic_write", side_effect=fail_profile_once):
            with self.assertRaises(OSError):
                codex_sync._apply_configs(self.codex_home, actions, "01234567-89ab-cdef-0123-456789abcdef")
        self.assertEqual(config.read_text(encoding="utf-8"), 'model = "before"\n')
        self.assertEqual(profile.read_text(encoding="utf-8"), 'model = "before-profile"\n')

    def test_codex_home_override_rejects_parent_traversal(self):
        with self.assertRaises(codex_sync.SyncError):
            codex_sync._resolve_codex_home("~/../escape")
        with self.assertRaises(codex_sync.SyncError):
            codex_sync._resolve_codex_home("relative/path")


if __name__ == "__main__":
    unittest.main()
