#!/usr/bin/env python3
"""Look up Active Directory users by username from Linux, like Get-ADUser.

Resolves a sAMAccountName (or userPrincipalName) to its distinguishedName
wherever the account sits in the directory, so callers never have to guess the
OU or assume CN equals the login name. Also provides bind-search-bind
authentication for web apps such as Flask.

Configuration, from the environment:
  AD_SERVER        ldaps://dc01.example.com (ldaps:// or ldap:// with StartTLS)
  AD_BASE_DN       dc=example,dc=com (the domain root, searched as a subtree)
  AD_BIND_USER     svc-ldap@example.com (UPN or DOMAIN\\user of a read-only account)
  AD_BIND_PASSWORD the service account password
  AD_CA_FILE       optional CA bundle for the domain controller certificate

Requires the optional dependency: pip install ".[ad]"

Examples:
  iato-ad-user jsmith
  iato-ad-user jsmith --attributes mail,department,memberOf
"""

import argparse
import json
import os
import ssl
import sys

try:
    from ldap3 import NONE, SUBTREE, Connection, Server, Tls
    from ldap3.core.exceptions import LDAPBindError
    from ldap3.utils.conv import escape_filter_chars
except ImportError:  # pragma: no cover - exercised only without the extra
    Connection = None

USER_FILTER = "(&(objectCategory=person)(objectClass=user)({attribute}={value}))"
ACCOUNT_DISABLED = 0x2


class AccountLookupError(Exception):
    """Raised when a username does not resolve to exactly one account."""


def _require_ldap3():
    if Connection is None:
        raise RuntimeError('ldap3 is not installed. Run: pip install ".[ad]"')


def user_filter(username):
    """Build an injection-safe filter for a sAMAccountName or UPN."""
    username = username.strip()
    if not username:
        raise ValueError("username is empty")
    attribute = "userPrincipalName" if "@" in username else "sAMAccountName"
    return USER_FILTER.format(attribute=attribute, value=escape_filter_chars(username))


def server_from_env(env=None):
    _require_ldap3()
    env = os.environ if env is None else env
    url = env["AD_SERVER"]
    tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=env.get("AD_CA_FILE"))
    return Server(url, use_ssl=url.lower().startswith("ldaps://"), tls=tls, get_info=NONE)


def _secure(conn):
    """Use StartTLS on ldap:// so no password crosses the wire in clear text."""
    if not conn.server.ssl:
        conn.open()
        conn.start_tls()
    return conn


def service_connection(env=None, server=None):
    env = os.environ if env is None else env
    server = server or server_from_env(env)
    conn = Connection(
        server,
        user=env["AD_BIND_USER"],
        password=env["AD_BIND_PASSWORD"],
        auto_referrals=False,
        raise_exceptions=False,
        read_only=True,
    )
    _secure(conn)
    if not conn.bind():
        raise LDAPBindError("Service account bind failed")
    return conn


def find_user(conn, base_dn, username, attributes=("distinguishedName",)):
    """Return the single entry for username, searching the whole subtree."""
    attrs = sorted(set(attributes) | {"distinguishedName", "userAccountControl"})
    conn.search(
        search_base=base_dn,
        search_filter=user_filter(username),
        search_scope=SUBTREE,
        attributes=attrs,
        size_limit=2,
    )
    # Referrals to other partitions come back as non-entry results; ignore them.
    entries = [e for e in conn.response or [] if e.get("type") == "searchResEntry"]
    if not entries:
        raise AccountLookupError(f"No account found for {username!r}")
    if len(entries) > 1:
        raise AccountLookupError(f"More than one account matches {username!r}")
    entry = entries[0]
    return {"dn": entry["dn"], **{k: v for k, v in entry["attributes"].items()}}


def get_user_dn(conn, base_dn, username):
    return find_user(conn, base_dn, username)["dn"]


def is_disabled(user):
    uac = user.get("userAccountControl") or 0
    if isinstance(uac, (list, tuple)):  # no schema loaded: values come back as lists
        uac = uac[0] if uac else 0
    return bool(int(uac) & ACCOUNT_DISABLED)


def authenticate(username, password, env=None, server=None):
    """Bind-search-bind. Returns the user's DN on success, None otherwise.

    1. Bind as the read-only service account.
    2. Find the user's real DN by username, in any OU.
    3. Bind as that DN with the supplied password.
    """
    if not password:
        # An empty password is an anonymous (unauthenticated) bind in LDAP and
        # would succeed. Refuse it outright.
        return None
    env = os.environ if env is None else env
    server = server or server_from_env(env)
    with service_connection(env, server) as svc:
        try:
            user = find_user(svc, env["AD_BASE_DN"], username)
        except AccountLookupError:
            return None
    if is_disabled(user):
        return None
    user_conn = Connection(server, user=user["dn"], password=password, auto_referrals=False, raise_exceptions=False)
    _secure(user_conn)
    try:
        return user["dn"] if user_conn.bind() else None
    finally:
        user_conn.unbind()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Look up an AD user by username, like Get-ADUser")
    parser.add_argument("username", help="sAMAccountName, or a UPN such as jsmith@example.com")
    parser.add_argument("--attributes", help="comma separated extra attributes to return")
    args = parser.parse_args(argv)
    attributes = ["distinguishedName"]
    if args.attributes:
        attributes += [a.strip() for a in args.attributes.split(",") if a.strip()]
    with service_connection() as conn:
        try:
            user = find_user(conn, os.environ["AD_BASE_DN"], args.username, attributes)
        except AccountLookupError as error:
            print(error, file=sys.stderr)
            return 1
    json.dump(user, sys.stdout, default=str, sort_keys=True, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
