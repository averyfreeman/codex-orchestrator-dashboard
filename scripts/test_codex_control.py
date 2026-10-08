import unittest

from scripts.codex_control import (
    _granted_permissions,
    _permissions_fit_profile,
    _route_is_valid,
    managed_thread_settings,
    project_notification,
    turn_sandbox_policy,
)


class DashboardCodexControlTests(unittest.TestCase):
    def test_profile_defaults_keep_home_sandbox_and_toggle_both_network_surfaces(self):
        home = "/home/operator"
        enabled = managed_thread_settings(home, True)
        disabled = managed_thread_settings(home, False)
        self.assertEqual(enabled["approvalPolicy"], "never")
        self.assertEqual(enabled["sandbox"], "workspace-write")
        self.assertEqual(enabled["runtimeWorkspaceRoots"], [home])
        self.assertEqual(enabled["config"]["web_search"], "live")
        self.assertTrue(enabled["config"]["sandbox_workspace_write"]["network_access"])
        self.assertEqual(disabled["config"]["web_search"], "disabled")
        self.assertFalse(disabled["config"]["sandbox_workspace_write"]["network_access"])
        self.assertEqual(turn_sandbox_policy(home, False), {
            "type": "workspaceWrite",
            "writableRoots": [home],
            "networkAccess": False,
        })

    def test_fleet_routes_are_limited_to_supported_transports_and_safe_aliases(self):
        self.assertTrue(_route_is_valid({"transport": "zerotier", "target": "operator@node-a.example.test", "hostKeyAlias": "fleet-node-a"}))
        self.assertFalse(_route_is_valid({"transport": "ssh", "target": "operator@node-a.example.test", "hostKeyAlias": "fleet-node-a"}))
        self.assertFalse(_route_is_valid({"transport": "zerotier", "target": "-oProxyCommand=evil", "hostKeyAlias": "fleet-dc2"}))

    def test_permission_expansion_stays_inside_the_profile(self):
        home = "/home/operator"
        self.assertTrue(_permissions_fit_profile({"fileSystem": {"write": ["/home/operator/work"]}}, home, True))
        self.assertFalse(_permissions_fit_profile({"fileSystem": {"write": ["/etc"]}}, home, True))
        self.assertFalse(_permissions_fit_profile({"network": {"enabled": True}}, home, False))
        self.assertTrue(_permissions_fit_profile({"network": {"enabled": True}}, home, True))

    def test_permission_grant_returns_only_the_requested_subset_inside_profile(self):
        requested = {
            "fileSystem": {"write": ["/home/operator/work", "/etc"], "entries": [
                {"path": {"type": "path", "path": "/home/operator/cache"}, "access": "read"},
                {"path": {"type": "special", "value": "root"}, "access": "write"},
            ]},
            "network": {"enabled": True},
            "unknown": {"enabled": True},
        }
        self.assertEqual(_granted_permissions(requested, "/home/operator", False), {
            "fileSystem": {
                "write": ["/home/operator/work"],
                "entries": [{"path": {"type": "path", "path": "/home/operator/cache"}, "access": "read"}],
            },
        })

    def test_terminal_output_is_never_projected_to_dashboard_events(self):
        event = project_notification({
            "method": "item/completed",
            "params": {"item": {"type": "commandExecution", "aggregatedOutput": "private command output", "command": "secret command"}},
        })
        self.assertEqual(event, {"type": "activity", "status": "completed", "kind": "commandExecution"})
        self.assertNotIn("private command output", str(event))
        self.assertNotIn("secret command", str(event))

    def test_turn_terminal_status_and_usage_are_content_free(self):
        completed = project_notification({"method": "turn/completed", "params": {"turn": {"id": "t-1", "status": "interrupted", "error": {"message": "private details"}}}})
        usage = project_notification({"method": "thread/tokenUsage/updated", "params": {"tokenUsage": {"total": {"inputTokens": 10, "cachedInputTokens": 2, "outputTokens": 5, "reasoningOutputTokens": 1, "totalTokens": 16}}}})
        self.assertEqual(completed, {"type": "completed", "status": "interrupted", "turnId": "t-1", "failed": True})
        self.assertEqual(usage["totalTokens"], 16)
        self.assertNotIn("private details", str(completed))


if __name__ == "__main__":
    unittest.main()
