# Intent Auditable Trust Object: BAU

Daily operational tooling in the IATO family. Where the other IATO repositories produce audit evidence, this one covers the routine, business-as-usual work an identity or systems administrator runs every day against Microsoft Entra ID (Azure AD) through Microsoft Graph.

Everything is read only, uses the Python standard library (the AD tool adds ldap3 as an optional extra), and fails closed: a run that cannot read every page writes nothing.

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

### `iato-ad-user`

Looks up an on-premises Active Directory user by username from Linux, the way `Get-ADUser` does on Windows. It returns the user's real `distinguishedName` wherever the account sits, so nothing assumes the OU or that the CN matches the login name.

- Searches the whole subtree from the domain root for `sAMAccountName`, or `userPrincipalName` when the input contains `@`, limited to user objects.
- Escapes the username before building the filter, so input such as `*)(cn=*` cannot widen the search.
- Refuses a username that matches no account or more than one.
- Uses LDAPS, or StartTLS on `ldap://`, and validates the domain controller's certificate.
- Does not chase referrals, so a search from the domain root does not hang on other partitions.

```
pip install ".[ad]"
iato-ad-user jsmith
iato-ad-user jsmith@example.com --attributes mail,department,memberOf
```

| Variable | Use |
|---|---|
| `AD_SERVER` | `ldaps://dc01.example.com`, or `ldap://` to use StartTLS |
| `AD_BASE_DN` | The domain root, for example `dc=example,dc=com` |
| `AD_BIND_USER`, `AD_BIND_PASSWORD` | A read-only service account, as a UPN or `DOMAIN\user` |
| `AD_CA_FILE` | Optional CA bundle for the domain controller certificate |

#### Signing in to a Flask app

`authenticate(username, password)` uses bind, search, then bind. It binds as the service account, finds the user's DN by username, then binds as that DN with the password the user typed. It returns the DN on success and `None` otherwise. Disabled accounts and empty passwords are refused, since an empty password is an unauthenticated bind that LDAP would accept.

```python
from flask import Flask, request, session, redirect, abort
from iato_bau.ad_users import authenticate

app = Flask(__name__)
app.secret_key = "load-from-your-secret-store"

@app.post("/login")
def login():
    dn = authenticate(request.form["username"], request.form["password"])
    if dn is None:
        abort(401)
    session["user_dn"] = dn
    return redirect("/")
```

## Entra authentication

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
iato_bau/entra_users.py   Entra user export command
iato_bau/ad_users.py      Active Directory lookup and bind-search-bind
tests/                    unit tests, no network needed
```

## Tests

```
python -m unittest discover -s tests -t . -v
```

CI runs the tests on Python 3.10 and 3.13 and checks the installed command starts.
