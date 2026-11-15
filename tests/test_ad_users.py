import functools
import unittest
from unittest.mock import patch

try:
    import ldap3
except ImportError:  # the ad extra is optional
    ldap3 = None

if ldap3:
    from iato_bau import ad_users

BASE = "dc=example,dc=com"
ENV = {"AD_BASE_DN": BASE, "AD_BIND_USER": "cn=svc,ou=Service,dc=example,dc=com", "AD_BIND_PASSWORD": "svc-pass"}


@unittest.skipIf(ldap3 is None, "ldap3 not installed")
class AdUsersTests(unittest.TestCase):
    def setUp(self):
        self.server = ldap3.Server("fake_dc", get_info=ldap3.NONE)
        mock_conn = functools.partial(ldap3.Connection, client_strategy=ldap3.MOCK_SYNC)
        patches = [
            patch("iato_bau.ad_users.Connection", mock_conn),
            patch("iato_bau.ad_users._secure", lambda conn: conn),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        seed = ldap3.Connection(self.server, client_strategy=ldap3.MOCK_SYNC)
        seed.strategy.add_entry("cn=svc,ou=Service,dc=example,dc=com", {"userPassword": "svc-pass", "objectClass": "user"})
        # CN differs from the login name and the account is two OUs deep.
        self._user(seed, "cn=Smith\\, John,ou=Auckland,ou=Staff,dc=example,dc=com", "jsmith", "pw", 512)
        self._user(seed, "cn=Disabled User,ou=Leavers,dc=example,dc=com", "gone", "pw", 514)
        self._user(seed, "cn=Dup One,ou=A,dc=example,dc=com", "dup", "pw", 512)
        self._user(seed, "cn=Dup Two,ou=B,dc=example,dc=com", "dup", "pw", 512)
        self.svc = ad_users.service_connection(ENV, self.server)

    @staticmethod
    def _user(conn, dn, sam, password, uac):
        conn.strategy.add_entry(dn, {
            "objectClass": ["top", "person", "user"], "objectCategory": "person",
            "sAMAccountName": sam, "userPrincipalName": f"{sam}@example.com",
            "distinguishedName": dn, "userPassword": password, "userAccountControl": uac,
        })

    def test_dn_found_when_cn_differs_from_username(self):
        self.assertEqual(ad_users.get_user_dn(self.svc, BASE, "jsmith"),
                         "cn=Smith\\, John,ou=Auckland,ou=Staff,dc=example,dc=com")

    def test_lookup_by_upn(self):
        self.assertIn("ou=Auckland", ad_users.get_user_dn(self.svc, BASE, "jsmith@example.com"))

    def test_unknown_user(self):
        with self.assertRaises(ad_users.AccountLookupError):
            ad_users.get_user_dn(self.svc, BASE, "nobody")

    def test_ambiguous_user_is_refused(self):
        with self.assertRaises(ad_users.AccountLookupError):
            ad_users.get_user_dn(self.svc, BASE, "dup")

    def test_filter_injection_is_escaped(self):
        self.assertEqual(ad_users.user_filter("*)(cn=*"),
                         "(&(objectCategory=person)(objectClass=user)(sAMAccountName=\\2a\\29\\28cn=\\2a))")
        with self.assertRaises(ad_users.AccountLookupError):
            ad_users.get_user_dn(self.svc, BASE, "*")

    def test_authenticate_success_returns_dn(self):
        self.assertIn("ou=Auckland", ad_users.authenticate("jsmith", "pw", ENV, self.server))

    def test_wrong_password(self):
        self.assertIsNone(ad_users.authenticate("jsmith", "bad", ENV, self.server))

    def test_empty_password_never_binds(self):
        self.assertIsNone(ad_users.authenticate("jsmith", "", ENV, self.server))

    def test_disabled_account_refused(self):
        self.assertIsNone(ad_users.authenticate("gone", "pw", ENV, self.server))

    def test_unknown_user_refused(self):
        self.assertIsNone(ad_users.authenticate("nobody", "pw", ENV, self.server))


if __name__ == "__main__":
    unittest.main()
