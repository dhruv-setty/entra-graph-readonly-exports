import io
import unittest
from unittest.mock import patch

from iato_bau import exports

NEXT = "https://graph.microsoft.com/v1.0/groups?$skiptoken=x"


class ExportsTests(unittest.TestCase):
    def test_roles_join_names_and_principals(self):
        pages = [
            {"value": [{"id": "r1", "displayName": "Global Reader"}]},
            {"value": [{"id": "a1", "roleDefinitionId": "r1", "principalId": "u1", "directoryScopeId": "/",
                        "principal": {"@odata.type": "#microsoft.graph.user", "userPrincipalName": "amy@contoso.com"}}]},
        ]
        with patch("iato_bau.graph.request_json", side_effect=pages) as req:
            rows = list(exports.export_roles("t"))
        self.assertEqual(rows[0]["roleName"], "Global Reader")
        self.assertEqual(rows[0]["principalType"], "user")
        self.assertEqual(rows[0]["principalName"], "amy@contoso.com")
        self.assertIn("$expand=principal", req.call_args_list[1].args[0])

    def test_group_members_page_through_groups_and_members(self):
        pages = [
            {"value": [{"id": "g1", "displayName": "Helpdesk"}], "@odata.nextLink": NEXT},
            {"value": [{"id": "m1", "@odata.type": "#microsoft.graph.user", "userPrincipalName": "a@c.com"}]},
            {"value": [{"id": "g2", "displayName": "Ops"}]},
            {"value": []},
        ]
        with patch("iato_bau.graph.request_json", side_effect=pages):
            rows = list(exports.export_group_members("t"))
        self.assertEqual([(r["groupName"], r["memberName"]) for r in rows], [("Helpdesk", "a@c.com")])

    def test_apps_report_nearest_secret_expiry(self):
        page = {"value": [{"id": "1", "passwordCredentials": [
            {"endDateTime": "2027-05-01T00:00:00Z"}, {"endDateTime": "2026-12-01T00:00:00Z"}]}]}
        with patch("iato_bau.graph.request_json", return_value=page):
            row = next(exports.export_apps("t"))
        self.assertEqual(row["secretCount"], 2)
        self.assertEqual(row["nextSecretExpiry"], "2026-12-01T00:00:00Z")

    def test_consents_flag_openid(self):
        page = {"value": [{"id": "c", "scope": " openid profile User.Read ", "consentType": "AllPrincipals"}]}
        with patch("iato_bau.graph.request_json", return_value=page):
            row = next(exports.export_consents("t"))
        self.assertTrue(row["includesOpenId"])
        self.assertEqual(row["scope"], "openid profile User.Read")

    def test_untrusted_next_link_is_refused(self):
        pages = [{"value": [], "@odata.nextLink": "https://evil.example/v1.0/groups"}]
        with patch("iato_bau.graph.request_json", side_effect=pages):
            with self.assertRaises(ValueError):
                list(exports.export_groups("t"))

    def test_csv_joins_lists(self):
        out = io.StringIO()
        exports.write_rows([{"id": "1", "groupTypes": ["Unified", "DynamicMembership"]}], "csv", out)
        self.assertIn("Unified;DynamicMembership", out.getvalue())


if __name__ == "__main__":
    unittest.main()
