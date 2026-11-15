import io
import unittest
from unittest.mock import patch

from iato_bau.entra_users import (
    acquire_token,
    fetch_users,
    users_url,
    write_csv,
)

PAGE_2 = "https://graph.microsoft.com/v1.0/users?$skiptoken=abc"


class EntraUsersTests(unittest.TestCase):
    def test_follows_next_link_until_exhausted(self):
        pages = [
            {"value": [{"id": "1"}, {"id": "2"}], "@odata.nextLink": PAGE_2},
            {"value": [{"id": "3"}]},
        ]
        with patch("iato_bau.graph.request_json", side_effect=pages) as request:
            users = list(fetch_users("token"))
        self.assertEqual([u["id"] for u in users], ["1", "2", "3"])
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[1].args[0], PAGE_2)

    def test_untrusted_next_link_is_refused(self):
        pages = [{"value": [{"id": "1"}], "@odata.nextLink": "https://attacker.example/v1.0/users"}]
        with patch("iato_bau.graph.request_json", side_effect=pages):
            with self.assertRaises(ValueError):
                list(fetch_users("token"))

    def test_url_uses_mail_and_max_page_size(self):
        url = users_url()
        self.assertIn("$top=999", url)
        self.assertIn("mail", url)
        self.assertNotIn("email", url)

    def test_filter_is_encoded(self):
        url = users_url(fields=("id",), page_size=10, odata_filter="accountEnabled eq true")
        self.assertIn("$filter=accountEnabled%20eq%20true", url)

    def test_page_size_bounds(self):
        with self.assertRaises(ValueError):
            users_url(page_size=1000)

    def test_csv_flattens_lists_and_nulls(self):
        out = io.StringIO()
        write_csv([{"id": "1", "businessPhones": ["a", "b"], "mail": None}], ("id", "businessPhones", "mail"), out)
        self.assertEqual(out.getvalue().splitlines()[1], "1,a;b,")

    def test_token_from_environment(self):
        self.assertEqual(acquire_token({"MS_GRAPH_TOKEN": "t"}), "t")

    def test_missing_credentials_raise(self):
        with self.assertRaises(RuntimeError):
            acquire_token({})


if __name__ == "__main__":
    unittest.main()
