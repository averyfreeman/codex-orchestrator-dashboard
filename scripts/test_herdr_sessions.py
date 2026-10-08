import unittest
import shlex
from unittest.mock import call, patch

from scripts.herdr_sessions import (
    HerdrControlError,
    _parse_sessions,
    _remote_command,
    _select_connection,
    run,
)


ZERO_TIER = {"transport": "zerotier", "target": "operator@node-a.example.test", "hostKeyAlias": "fleet-node-a"}
TAILSCALE = {"transport": "tailscale", "target": "operator@node-a-tailnet.example.test", "hostKeyAlias": "fleet-node-a"}


class DashboardHerdrSessionTests(unittest.TestCase):
    def test_session_parser_returns_only_bounded_session_metadata(self):
        sessions = _parse_sessions('{"sessions":[{"name":"default","running":true,"default":true,"paneText":"secret"},{"name":"work","running":false}]}')
        self.assertEqual(sessions, [
            {"name": "default", "running": True, "default": True},
            {"name": "work", "running": False, "default": False},
        ])

    def test_route_validation_rejects_non_ascii_and_shell_tokens(self):
        host = {"sshRoutes": [ZERO_TIER, TAILSCALE]}
        with patch("scripts.herdr_sessions._run_list", return_value=[]):
            self.assertEqual(_select_connection(host)[0], ZERO_TIER)
        for invalid in ({**ZERO_TIER, "target": "avery@dc2;touch /tmp/no"}, {**ZERO_TIER, "target": "avery@høst"}):
            with self.subTest(target=invalid["target"]), self.assertRaises(HerdrControlError):
                _select_connection({"sshRoutes": [invalid]})

    def test_read_only_route_falls_back_in_configured_order(self):
        host = {"sshRoutes": [ZERO_TIER, TAILSCALE]}
        with patch("scripts.herdr_sessions._run_list", side_effect=[HerdrControlError("unavailable"), []]) as list_sessions:
            route, sessions = _select_connection(host)
        self.assertEqual(route, TAILSCALE)
        self.assertEqual(sessions, [])
        self.assertEqual(list_sessions.call_args_list, [call(host, ZERO_TIER), call(host, TAILSCALE)])

    def test_default_session_cannot_be_started_or_stopped(self):
        host = {"local": True}
        with patch("scripts.herdr_sessions._select_connection") as select:
            for action in ("start", "stop"):
                with self.subTest(action=action), self.assertRaises(HerdrControlError):
                    run({"host": host, "action": action, "name": "default"})
            select.assert_not_called()

    def test_named_session_start_mutates_once_over_the_route_that_passed_listing(self):
        host = {"sshRoutes": [ZERO_TIER, TAILSCALE]}
        with patch("scripts.herdr_sessions._select_connection", return_value=(ZERO_TIER, [{"name": "work", "running": False}])):
            with patch("scripts.herdr_sessions._mutate") as mutate:
                with patch("scripts.herdr_sessions._run_list", return_value=[{"name": "work", "running": True}]):
                    result = run({"host": host, "action": "start", "name": "work"})
        self.assertEqual(result["state"], "running")
        mutate.assert_called_once_with(host, ZERO_TIER, "start", "work")

    def test_shell_command_uses_validated_session_as_one_quoted_argument(self):
        command = _remote_command("start", "work-session")
        self.assertIn("export HERDR_ENV=1", command)
        self.assertIn(f"--session {shlex.quote('work-session')} server", command)
        injected = _remote_command("start", "work;touch /tmp/not-run")
        self.assertIn(f"--session {shlex.quote('work;touch /tmp/not-run')} server", injected)


if __name__ == "__main__":
    unittest.main()
