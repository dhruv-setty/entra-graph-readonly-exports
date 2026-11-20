# Intent Auditable Trust Object: BAU

Daily operational tooling in the IATO family. Where the other IATO repositories produce audit evidence, this one covers the routine, business-as-usual work an identity or systems administrator runs every day against Microsoft Entra ID (Azure AD) through Microsoft Graph.

Everything is read only, uses the Python standard library, and fails closed: a run that cannot read every page writes nothing.

## Tools

### `iato-entra-users`

Exports every user in the tenant to JSON or CSV.

- Requests pages of 999, the Graph maximum, and follows `@odata.nextLink` until none is returned, so tenants of any size come back whole.
- Refuses a next link that does not point at `https://graph.microsoft.com/v1.0/`, so the bearer token is never sent anywhere else.
- Retries throttling (429) and server errors, honouring `Retry-After`, capped at 60 seconds.
- Selects the user's address as `mail`. Graph has no `email` property on user.

```
pip install .
iato-entra-users > users.json
iato-entra-users --format csv --output users.csv
iato-entra-users --filter "accountEnabled eq true" --fields id,userPrincipalName,mail,department
```

Default fields: `id`, `userPrincipalName`, `displayName`, `givenName`, `surname`, `mail`, `jobTitle`, `department`, `officeLocation`, `companyName`, `employeeId`, `mobilePhone`, `businessPhones`, `accountEnabled`, `userType`, `createdDateTime`. In CSV, list values such as `businessPhones` are joined with `;`.

### `entra-export`

Read-only exports of the directory around the users: who holds which admin role, which groups exist and who is in them, which apps are registered, and what they have been consented to. Every export pages through `@odata.nextLink` with the same trusted-host check and retries as the user export, and writes nothing if a page fails.

```
entra-export roles --format csv --output roles.csv
entra-export group-members --format csv --output memberships.csv
entra-export apps > apps.json
entra-export consents --format csv --output consents.csv
entra-export oidc --tenant contoso.onmicrosoft.com
```

| Export | What it lists | Application permission |
|---|---|---|
| `roles` | Directory role assignments (RBAC), each joined to its role name and the user, group or app holding it | `RoleManagement.Read.Directory` |
| `groups` | Every group: security or Microsoft 365, dynamic membership rule, synced from on-premises | `Group.Read.All` |
| `group-members` | One row per membership, across every group | `GroupMember.Read.All` |
| `apps` | App registrations, with secret and certificate counts and the nearest expiry date | `Application.Read.All` |
| `sps` | Service principals (enterprise applications) | `Application.Read.All` |
| `consents` | Delegated OAuth 2.0 grants, flagging those that include the OpenID `openid` scope | `DelegatedPermissionGrant.Read.All` |
| `oidc` | The tenant's public OpenID Connect discovery document: issuer, endpoints, signing keys URL | none, no token is sent |

## Authentication

Register an app in Microsoft Entra, add the application permissions for the exports you run (`User.Read.All` for users, and those in the table above), and grant admin consent. Every permission is a read permission.

Then provide either:

| Variable | Use |
|---|---|
| `MS_GRAPH_TOKEN` | An application access token for Graph, used as is. |
| `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` | Runs the OAuth 2.0 client credentials flow for `https://graph.microsoft.com/.default`. |

Keep the secret in a secret store or pipeline variable, never in the repository.

## Layout

```
iato_bau/graph.py         trusted-host check, retries, @odata.nextLink paging
iato_bau/entra_users.py   user export command
iato_bau/exports.py       roles, groups, apps, consents and OIDC exports
docs/screenshots/         sample output from a developer tenant
tests/                    unit tests, no network needed
```

## Tests

```
python -m unittest discover -s tests -t . -v
```

CI runs the tests on Python 3.10 and 3.13 and checks the installed command starts.

## Screenshots

Sample runs live in `docs/screenshots/`. They come from a Microsoft 365 developer tenant with sample users only, never a production or employer tenant, so no real names, addresses or tenant IDs appear.

## Microsoft Graph references

- [Paging Microsoft Graph data](https://learn.microsoft.com/en-us/graph/paging)
- [Microsoft Graph throttling guidance](https://learn.microsoft.com/en-us/graph/throttling)
- [List users](https://learn.microsoft.com/en-us/graph/api/user-list)
- [List role assignments](https://learn.microsoft.com/en-us/graph/api/rbacapplication-list-roleassignments) and [role definitions](https://learn.microsoft.com/en-us/graph/api/rbacapplication-list-roledefinitions)
- [List groups](https://learn.microsoft.com/en-us/graph/api/group-list) and [group members](https://learn.microsoft.com/en-us/graph/api/group-list-members)
- [List applications](https://learn.microsoft.com/en-us/graph/api/application-list) and [service principals](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-list)
- [List oauth2PermissionGrants](https://learn.microsoft.com/en-us/graph/api/oauth2permissiongrant-list)
- [OpenID Connect on the Microsoft identity platform](https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc)
- [OAuth 2.0 client credentials flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow)
- [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)
