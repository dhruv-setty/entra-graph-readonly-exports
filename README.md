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

## Authentication

Register an app in Microsoft Entra, add the `User.Read.All` application permission, and grant admin consent. Nothing else is needed.

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
tests/                    unit tests, no network needed
```

## Tests

```
python -m unittest discover -s tests -t . -v
```

CI runs the tests on Python 3.10 and 3.13 and checks the installed command starts.
