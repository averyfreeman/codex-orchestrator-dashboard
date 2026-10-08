import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
from codex_recovery import REMOTE_START_COMMAND, RecoveryError, recover_host


class CodexRecoveryTests(unittest.TestCase):
    def test_starts_local_daemon_with_fixed_arguments(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        with patch("codex_recovery._codex_path", return_value="/usr/local/bin/codex"):
            transport = recover_host({"slug": "maccauley", "local": True}, run)

        self.assertEqual(transport, "local")
        self.assertEqual(run.call_args.args[0], ["/usr/local/bin/codex", "app-server", "daemon", "start"])
        self.assertEqual(run.call_args.kwargs["timeout"], 60)

    def test_tries_zerotier_before_tailscale_and_uses_strict_host_keys(self):
        routes = [
            {"transport": "zerotier", "target": "operator@192.0.2.15", "hostKeyAlias": "fleet-dc2"},
            {"transport": "tailscale", "target": "operator@203.0.113.5", "hostKeyAlias": "fleet-dc2"},
        ]
        run = Mock(side_effect=[
            subprocess.CompletedProcess([], 255, "", "unreachable"),
            subprocess.CompletedProcess([], 0, "", ""),
        ])

        transport = recover_host({"slug": "dc2", "sshRoutes": routes}, run)

        self.assertEqual(transport, "tailscale")
        first = run.call_args_list[0].args[0]
        second = run.call_args_list[1].args[0]
        self.assertEqual(first[first.index("-o") + 1], "BatchMode=yes")
        self.assertIn("StrictHostKeyChecking=yes", first)
        self.assertIn("HostKeyAlias=fleet-dc2", first)
        self.assertEqual(first[-2], routes[0]["target"])
        self.assertEqual(second[-2], routes[1]["target"])
        self.assertEqual(first[-1], REMOTE_START_COMMAND)

    def test_rejects_invalid_routes_without_running_a_command(self):
        run = Mock()
        with self.assertRaises(RecoveryError):
            recover_host({"slug": "dc2", "sshRoutes": [
                {"transport": "zerotier", "target": "operator@192.0.2.15; touch /tmp/no", "hostKeyAlias": "fleet-dc2"},
            ]}, run)
        run.assert_not_called()

    def test_hides_remote_command_output_on_failure(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 1, "secret output", "credential detail"))
        host = {"slug": "dc2", "sshRoutes": [
            {"transport": "zerotier", "target": "operator@192.0.2.15", "hostKeyAlias": "fleet-dc2"},
        ]}

        with self.assertRaises(RecoveryError) as failure:
            recover_host(host, run)

        self.assertNotIn("secret output", str(failure.exception))
        self.assertNotIn("credential detail", str(failure.exception))


if __name__ == "__main__":
    unittest.main()
