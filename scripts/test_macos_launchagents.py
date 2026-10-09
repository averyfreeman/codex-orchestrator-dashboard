import importlib.util
import json
import plistlib
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("install_macos_launchagents.py")
SPEC = importlib.util.spec_from_file_location("install_macos_launchagents", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class MacOSLaunchAgentTests(unittest.TestCase):
    def test_inventory_codex_home_override_precedes_process_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "user"
            home.mkdir()
            inventory = Path(directory) / "fleet.json"
            inventory.write_text(json.dumps([{"local": True, "codexHome": "~/.codex-custom"}]))
            result = module.resolve_codex_home(home, inventory, {"CODEX_HOME": "/tmp/environment-codex"})
        self.assertEqual(result, (home / ".codex-custom").resolve())

    def test_local_environment_precedes_default_when_inventory_has_no_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "user"
            home.mkdir()
            inventory = Path(directory) / "fleet.json"
            inventory.write_text(json.dumps([{"local": True}]))
            result = module.resolve_codex_home(home, inventory, {"CODEX_HOME": "~/from-env"})
        self.assertEqual(result, (home / "from-env").resolve())

    def test_multiple_local_inventory_overrides_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "fleet.json"
            inventory.write_text(json.dumps([
                {"local": True, "codexHome": "~/.codex-a"},
                {"local": True, "codexHome": "~/.codex-b"},
            ]))
            with self.assertRaisesRegex(ValueError, "multiple local host"):
                module.resolve_codex_home(root, inventory, {})

    def test_codex_agent_starts_and_rechecks_remote_control(self) -> None:
        agent = module.render_agent(
            "codex-app-server-ensure",
            Path("/Users/example"),
            "/Users/example/.local/bin/codex",
            "/opt/homebrew/bin/herdr",
        )
        self.assertEqual(agent["ProgramArguments"], [
            "/Users/example/.local/bin/codex", "app-server", "daemon", "start"
        ])
        self.assertTrue(agent["RunAtLoad"])
        self.assertEqual(agent["StartInterval"], 300)
        self.assertEqual(agent["EnvironmentVariables"]["CODEX_HOME"], "/Users/example/.codex")

    def test_herdr_agent_is_kept_alive_under_the_user(self) -> None:
        agent = module.render_agent(
            "herdr-server",
            Path("/Users/example"),
            "/Users/example/.local/bin/codex",
            "/opt/homebrew/bin/herdr",
        )
        self.assertEqual(agent["ProgramArguments"], ["/opt/homebrew/bin/herdr", "server"])
        self.assertTrue(agent["RunAtLoad"])
        self.assertTrue(agent["KeepAlive"])
        self.assertEqual(agent["EnvironmentVariables"]["HOME"], "/Users/example")

    def test_templates_are_valid_plists(self) -> None:
        for name in module.AGENT_NAMES:
            rendered = module.render_agent(
                name,
                Path("/Users/example"),
                "/Users/example/.local/bin/codex",
                "/opt/homebrew/bin/herdr",
            )
            self.assertIsInstance(rendered, dict)
            self.assertEqual(rendered["Label"], module.AGENTS[name]["label"])

    def test_template_paths_are_xml_escaped(self) -> None:
        agent = module.render_agent(
            "herdr-server",
            Path("/Users/example & user"),
            "/Users/example & user/.local/bin/codex",
            "/opt/homebrew/bin/herdr",
        )
        self.assertEqual(agent["EnvironmentVariables"]["HOME"], "/Users/example & user")


if __name__ == "__main__":
    unittest.main()
