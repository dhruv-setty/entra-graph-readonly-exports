#!/usr/bin/env python3
"""Read-only Microsoft Entra exports through Microsoft Graph: roles, groups, apps and consents.

Every export follows @odata.nextLink until Graph stops returning one, and
fails closed: if any page fails after retries, nothing is written.

Exports and the application permission each needs (read only):
  roles           directory role assignments, joined to role names    RoleManagement.Read.Directory
  groups          every group with its type and dynamic rule          Group.Read.All
  group-members   one row per group membership                        GroupMember.Read.All
  apps            app registrations with secret and cert expiry       Application.Read.All
  sps             service principals (enterprise apps)                Application.Read.All
  consents        delegated OAuth 2.0 / OpenID permission grants      DelegatedPermissionGrant.Read.All

Authentication is the same as iato-entra-users (MS_GRAPH_TOKEN, or the
AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET client credentials).

Examples:
  entra-export roles --format csv --output roles.csv
  entra-export consents > consents.json
  entra-export oidc --tenant contoso.onmicrosoft.com
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from iato_bau.entra_users import LOGIN_ROOT, MAX_PAGE_SIZE, acquire_token
from iato_bau.graph import GRAPH_ROOT, paged


def graph_url(path, select=None, top=MAX_PAGE_SIZE, expand=None):
    params = []
    if select:
        params.append(("$select", ",".join(select)))
    if expand:
        params.append(("$expand", expand))
    if top:
        params.append(("$top", str(top)))
    query = "?" + urlencode(params, safe="$,()", quote_via=quote) if params else ""
    return f"{GRAPH_ROOT}/{path}{query}"


def _odata_type(item):
    return (item.get("@odata.type") or "").rsplit(".", 1)[-1]


def export_roles(token):
    """One row per directory role assignment, with the role and principal named."""
    names = {
        d["id"]: d.get("displayName", "")
        for d in paged(graph_url("roleManagement/directory/roleDefinitions", ("id", "displayName")), token)
    }
    url = graph_url("roleManagement/directory/roleAssignments", top=None, expand="principal")
    for a in paged(url, token):
        p = a.get("principal") or {}
        yield {
            "assignmentId": a.get("id"),
            "roleDefinitionId": a.get("roleDefinitionId"),
            "roleName": names.get(a.get("roleDefinitionId"), ""),
            "directoryScopeId": a.get("directoryScopeId"),
            "principalId": a.get("principalId"),
            "principalType": _odata_type(p),
            "principalName": p.get("userPrincipalName") or p.get("displayName") or "",
        }


GROUP_FIELDS = ("id", "displayName", "mail", "mailEnabled", "securityEnabled", "groupTypes",
                "membershipRule", "onPremisesSyncEnabled", "createdDateTime")


def export_groups(token):
    for g in paged(graph_url("groups", GROUP_FIELDS), token):
        yield {f: g.get(f) for f in GROUP_FIELDS}


def export_group_members(token):
    for g in paged(graph_url("groups", ("id", "displayName")), token):
        url = graph_url(f"groups/{quote(g['id'], safe='')}/members", ("id", "displayName", "userPrincipalName"))
        for m in paged(url, token):
            yield {
                "groupId": g["id"],
                "groupName": g.get("displayName"),
                "memberId": m.get("id"),
                "memberType": _odata_type(m),
                "memberName": m.get("userPrincipalName") or m.get("displayName") or "",
            }


def _nearest_expiry(credentials):
    ends = sorted(c["endDateTime"] for c in credentials or [] if c.get("endDateTime"))
    return ends[0] if ends else ""


def export_apps(token):
    select = ("id", "appId", "displayName", "signInAudience", "createdDateTime",
              "passwordCredentials", "keyCredentials", "requiredResourceAccess")
    for a in paged(graph_url("applications", select), token):
        yield {
            "id": a.get("id"),
            "appId": a.get("appId"),
            "displayName": a.get("displayName"),
            "signInAudience": a.get("signInAudience"),
            "createdDateTime": a.get("createdDateTime"),
            "secretCount": len(a.get("passwordCredentials") or []),
            "nextSecretExpiry": _nearest_expiry(a.get("passwordCredentials")),
            "certCount": len(a.get("keyCredentials") or []),
            "nextCertExpiry": _nearest_expiry(a.get("keyCredentials")),
            "apiPermissionCount": sum(len(r.get("resourceAccess") or []) for r in a.get("requiredResourceAccess") or []),
        }


SP_FIELDS = ("id", "appId", "displayName", "servicePrincipalType", "accountEnabled", "appOwnerOrganizationId")


def export_sps(token):
    for s in paged(graph_url("servicePrincipals", SP_FIELDS), token):
        yield {f: s.get(f) for f in SP_FIELDS}


def export_consents(token):
    """Delegated grants. 'scope' is space separated, e.g. 'openid profile User.Read'."""
    for c in paged(graph_url("oauth2PermissionGrants", top=None), token):
        scopes = (c.get("scope") or "").split()
        yield {
            "id": c.get("id"),
            "clientId": c.get("clientId"),
            "resourceId": c.get("resourceId"),
            "consentType": c.get("consentType"),
            "principalId": c.get("principalId") or "",
            "scope": " ".join(scopes),
            "includesOpenId": "openid" in scopes,
        }


def openid_configuration(tenant):
    """Public OpenID Connect discovery document. No token is sent."""
    url = f"{LOGIN_ROOT}/{quote(tenant, safe='')}/v2.0/.well-known/openid-configuration"
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=60) as response:
        doc = json.loads(response.read().decode("utf-8"))
    keys = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri", "userinfo_endpoint",
            "end_session_endpoint", "scopes_supported", "response_types_supported", "id_token_signing_alg_values_supported")
    return [{k: doc.get(k) for k in keys}]


EXPORTS = {
    "roles": export_roles,
    "groups": export_groups,
    "group-members": export_group_members,
    "apps": export_apps,
    "sps": export_sps,
    "consents": export_consents,
}


def _flatten(value):
    if isinstance(value, list):
        return ";".join(str(v) for v in value)
    return "" if value is None else value


def write_rows(rows, fmt, handle):
    if fmt == "csv":
        fields = list(rows[0]) if rows else []
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _flatten(v) for k, v in row.items()})
    else:
        json.dump(rows, handle, sort_keys=True)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", choices=sorted(EXPORTS) + ["oidc"])
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    parser.add_argument("--output", help="file to write; stdout when omitted")
    parser.add_argument("--tenant", help="tenant id or domain, for oidc (defaults to AZURE_TENANT_ID)")
    args = parser.parse_args(argv)

    if args.export == "oidc":
        import os
        tenant = args.tenant or os.environ.get("AZURE_TENANT_ID")
        if not tenant:
            parser.error("oidc needs --tenant or AZURE_TENANT_ID")
        rows = openid_configuration(tenant)
    else:
        # Collect fully before writing so a failed page never leaves a partial file.
        rows = list(EXPORTS[args.export](acquire_token()))

    handle = open(args.output, "w", encoding="utf-8", newline="") if args.output else sys.stdout
    try:
        write_rows(rows, args.format, handle)
    finally:
        if args.output:
            handle.close()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"Exported {len(rows)} {args.export} rows at {stamp}", file=sys.stderr)


if __name__ == "__main__":
    main()
