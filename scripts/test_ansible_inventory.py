import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "ansible" / "inventory.py"
SPEC = importlib.util.spec_from_file_location("fleet_ansible_inventory", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class AnsibleInventoryTests(unittest.TestCase):
    def test_remote_codex_home_override_is_passed_to_ansible(self) -> None:
        host = {
            "slug": "remote",
            "local": False,
            "codexHome": "~/.codex-work",
            "sshRoutes": [{
                "target": "operator@example.invalid",
                "hostKeyAlias": "remote-host",
                "transport": "tailscale",
            }],
        }
        with patch.object(module, "load_hosts", return_value=[host]), patch.object(module, "ssh_available", return_value=True):
            result = module.inventory()
        self.assertEqual(result["_meta"]["hostvars"]["remote"]["fleet_codex_home_override"], "~/.codex-work")

    def test_invalid_codex_home_override_excludes_host_before_ssh(self) -> None:
        host = {
            "slug": "remote",
            "local": False,
            "codexHome": "~/../escape",
            "sshRoutes": [{
                "target": "operator@example.invalid",
                "hostKeyAlias": "remote-host",
                "transport": "tailscale",
            }],
        }
        with patch.object(module, "load_hosts", return_value=[host]), patch.object(module, "ssh_available") as ssh_available:
            result = module.inventory()
        ssh_available.assert_not_called()
        self.assertEqual(result["linux_fleet"]["hosts"], [])


if __name__ == "__main__":
    unittest.main()
