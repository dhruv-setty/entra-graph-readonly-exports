#!/usr/bin/env python3
"""Export every Microsoft Entra (Azure AD) user through Microsoft Graph.

Follows @odata.nextLink until the directory is exhausted, so tenants larger
than one page (100 users by default, 999 at most) are returned whole. The
export fails closed: if any page fails after retries, nothing is written.

Authentication, in order of preference:
  1. MS_GRAPH_TOKEN: an application access token for Graph.
  2. AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET: the client
     credentials flow is run against the Microsoft identity platform.

The app needs the User.Read.All application permission (read only).

Examples:
  iato-entra-users > users.json
  iato-entra-users --format csv --output users.csv
  iato-entra-users --filter "accountEnabled eq true"
"""

import argparse
import csv
import json
import os
import sys
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from iato_bau.graph import GRAPH_ROOT, paged

LOGIN_ROOT = "https://login.microsoftonline.com"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
MAX_PAGE_SIZE = 999

# Graph has no "email" property on user; the address is "mail".
DEFAULT_FIELDS = (
    "id",
    "userPrincipalName",
    "displayName",
    "givenName",
    "surname",
    "mail",
    "jobTitle",
    "department",
    "officeLocation",
    "companyName",
    "employeeId",
    "mobilePhone",
    "businessPhones",
    "accountEnabled",
    "userType",
    "createdDateTime",
)


def acquire_token(env=None):
    """Return a Graph token from MS_GRAPH_TOKEN or the client credentials flow."""
    env = os.environ if env is None else env
    token = env.get("MS_GRAPH_TOKEN")
    if token:
        return token
    tenant = env.get("AZURE_TENANT_ID")
    client_id = env.get("AZURE_CLIENT_ID")
    secret = env.get("AZURE_CLIENT_SECRET")
    if not (tenant and client_id and secret):
        raise RuntimeError(
            "Set MS_GRAPH_TOKEN, or AZURE_TENANT_ID, AZURE_CLIENT_ID and AZURE_CLIENT_SECRET"
        )
    url = f"{LOGIN_ROOT}/{quote(tenant, safe='')}/oauth2/v2.0/token"
    body = urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": secret,
            "scope": GRAPH_SCOPE,
        }
    ).encode("ascii")
    request = Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if "access_token" not in payload:
        raise RuntimeError("Token response did not contain an access_token")
    return payload["access_token"]


def users_url(fields=DEFAULT_FIELDS, page_size=MAX_PAGE_SIZE, odata_filter=None):
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    params = [("$select", ",".join(fields)), ("$top", str(page_size))]
    if odata_filter:
        params.append(("$filter", odata_filter))
    return f"{GRAPH_ROOT}/users?" + urlencode(params, safe="$,", quote_via=quote)


def fetch_users(token, fields=DEFAULT_FIELDS, page_size=MAX_PAGE_SIZE, odata_filter=None):
    """Yield every user, page by page, until Graph stops returning nextLink."""
    yield from paged(users_url(fields, page_size, odata_filter), token)


def _flatten(value):
    if isinstance(value, list):
        return ";".join(str(item) for item in value)
    if value is None:
        return ""
    return value


def write_csv(users, fields, handle):
    writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
    writer.writeheader()
    for user in users:
        writer.writerow({field: _flatten(user.get(field)) for field in fields})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    parser.add_argument("--output", help="file to write; stdout when omitted")
    parser.add_argument("--fields", help="comma separated Graph user properties")
    parser.add_argument("--filter", dest="odata_filter", help="OData $filter expression")
    parser.add_argument("--page-size", type=int, default=MAX_PAGE_SIZE)
    args = parser.parse_args(argv)

    fields = tuple(f.strip() for f in args.fields.split(",")) if args.fields else DEFAULT_FIELDS
    # Collect fully before writing so a failed page never leaves a partial file.
    users = list(fetch_users(acquire_token(), fields, args.page_size, args.odata_filter))

    handle = open(args.output, "w", encoding="utf-8", newline="") if args.output else sys.stdout
    try:
        if args.format == "csv":
            write_csv(users, fields, handle)
        else:
            json.dump(users, handle, sort_keys=True)
            handle.write("\n")
    finally:
        if args.output:
            handle.close()
    print(f"Exported {len(users)} users", file=sys.stderr)


if __name__ == "__main__":
    main()
