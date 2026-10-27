# Sign-in with Amazon Cognito and Entra ID

This guide sets up the sign-in of a generated app with a user pool of
Amazon Cognito, whose identity provider is Microsoft Entra ID over SAML.
The staff of a company then sign in with their company account, and the
app keeps no passwords.

The generated apps speak only OpenID Connect
([ADR 0020](adr/0020-providers.md)). The user pool does the SAML part:

1. The app sends the browser to the authorization endpoint of the user
   pool, with the parameter `identity_provider=EntraID`.
2. The user pool sends the browser to Entra ID with a SAML request.
   The user signs in at Entra ID.
3. Entra ID sends a SAML assertion to the user pool
   (`/saml2/idpresponse`). The user pool sends the browser back to the
   callback of the app with a code.
4. The app changes the code for an ID token at the token endpoint of the
   user pool, checks the token, and starts the session of the user.

## Contents

- [The app definition](#the-app-definition)
- [Step 1: the user pool and its domain](#step-1-the-user-pool-and-its-domain)
- [Step 2: Entra ID as a SAML provider](#step-2-entra-id-as-a-saml-provider)
- [Step 3: the app client](#step-3-the-app-client)
- [Step 4: the settings of the apps](#step-4-the-settings-of-the-apps)
- [The verified email address](#the-verified-email-address)
- [Roles from the groups of Entra ID](#roles-from-the-groups-of-entra-id)
- [Limits](#limits)
- [Checks without a user pool](#checks-without-a-user-pool)

## The app definition

```yaml
auth:
  user_entity: Person
  username_field: email
  password: false
  providers:
    company:
      title: Company account
      issuer: https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_Example
      client_id_env: COMPANY_CLIENT_ID
      client_secret_env: COMPANY_CLIENT_SECRET
      authorize_params: { identity_provider: EntraID }
      trust_email: true
      create_users: true
      default_role: staff
      claims: { name: name }
      roles:
        claim: "custom:groups"
        map:
          0b8e7f5c-2d4a-4c1e-9f3a-6a1d2b3c4d5e: admin
          5f6e7d8c-9b0a-4f1e-8d2c-3b4a5c6d7e8f: staff
```

- `issuer` is the issuer of the user pool:
  `https://cognito-idp.<region>.amazonaws.com/<user pool ID>`. The
  discovery document of the user pool is under it. The authorization and
  the token endpoints are on the domain of the user pool, and the apps
  read them from the discovery document.
- `authorize_params.identity_provider` is the name of the SAML provider
  in the user pool (step 2). Without it, the user pool shows its own
  sign-in page with a button for each provider.
- `trust_email` accepts the email address of a SAML user. See
  [The verified email address](#the-verified-email-address).
- `roles` gives the role of the user from the groups of Entra ID at each
  sign-in. See [Roles from the groups of Entra ID](#roles-from-the-groups-of-entra-id).
- `tests/fixtures/cognito-sign-in.yaml` is a complete definition.

## Step 1: the user pool and its domain

1. Make a user pool in Amazon Cognito, or use one that exists. Write
   down its ID, for example `eu-west-1_Example`.
2. Give the user pool a domain: a prefix domain
   (`https://<prefix>.auth.<region>.amazoncognito.com`) or a custom
   domain. The steps below call it `<user pool domain>`.

## Step 2: Entra ID as a SAML provider

In Entra ID:

1. Add an enterprise application (an application that is not in the
   gallery), and select SAML for its single sign-on.
2. Set the identifier (entity ID) to
   `urn:amazon:cognito:sp:<user pool ID>`.
3. Set the reply URL (assertion consumer service URL) to
   `https://<user pool domain>/saml2/idpresponse`.
4. Keep the claims of the email address and of the name.
5. Assign the users or the groups that may sign in.
6. Copy the URL of the federation metadata of the application.

In the user pool:

1. Add a SAML identity provider with the name `EntraID`. This name is
   the value of `authorize_params.identity_provider`.
2. Give it the URL of the federation metadata of Entra ID.
3. Map the attributes of the SAML assertion to the attributes of the
   user pool:

   | Attribute of the user pool | Attribute of the SAML assertion                                      |
   | -------------------------- | -------------------------------------------------------------------- |
   | `email`                    | `http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress` |
   | `name`                     | `http://schemas.microsoft.com/identity/claims/displayname`           |

## Step 3: the app client

Make an app client in the user pool:

1. Give it a client secret. The apps send the client ID and the secret
   to the token endpoint with the basic scheme.
2. Select the identity provider `EntraID`.
3. Select the authorization code grant, and the scopes `openid`,
   `email`, and `profile`.
4. Add the callback URL of each app:
   - The Next.js app: `<PUBLIC_URL>/auth/providers/company/callback`.
   - The FastAPI app (also for the React app with
     `x-react-data: api`): `<PUBLIC_URL of the FastAPI app>/auth/providers/company/callback`.
5. Copy the client ID and the client secret.

## Step 4: the settings of the apps

| Setting                 | Value                                                                    |
| ----------------------- | ------------------------------------------------------------------------ |
| `COMPANY_CLIENT_ID`     | The client ID of the app client.                                         |
| `COMPANY_CLIENT_SECRET` | The client secret of the app client.                                     |
| `COMPANY_ISSUER`        | Only for another user pool than the one of the definition, for example a test pool. |
| `PUBLIC_URL`            | The URL of the app. The callback URL starts with it.                     |
| `CORS_ORIGINS`          | The FastAPI app with the React app: the origin of the React app.         |

The names of the variables come from the definition: the provider
`company` gives `COMPANY_ISSUER`, and `client_id_env` and
`client_secret_env` give the others.

## The verified email address

The apps find the user by the claim `email` of the ID token. A provider
that lets users choose an address that it did not verify could give a
sign-in as another user. Thus the apps refuse an ID token with
`email_verified: false` ([ADR 0020](adr/0020-providers.md)).

The user pool sets `email_verified` to `false` for a SAML user when no
attribute of the SAML assertion maps to it, and Entra ID sends no such
attribute. There are two fixes:

- `trust_email: true` on the provider. The apps then accept the address
  of each ID token of the provider. This is safe when the provider gives
  only addresses that the company controls, as a user pool does whose
  only identity provider is the single-tenant Entra ID of the company.
  Do not use it for a user pool that also lets users sign up with their
  own address.
- Map an attribute of the SAML assertion to `email_verified` in the user
  pool, with the value `true` for each user. Then the provider needs no
  `trust_email`.

## Roles from the groups of Entra ID

With `roles`, the apps set the role of the user at each sign-in from
the groups of the user in Entra ID. The company then manages the rights
of the staff in Entra ID. A change of the groups changes the role at the
next sign-in.

In Entra ID, in the single sign-on of the enterprise application:

1. Add a group claim. Select "Groups assigned to the application", so
   that the assertion has only the groups that the app knows. Entra ID
   sends at most 150 groups in a SAML assertion: with more, it sends a
   link to Microsoft Graph in place of the groups, and the apps do not
   follow it.
2. Keep the source attribute "Group ID". Entra ID then sends the object
   IDs of the groups, not their names. The keys of `roles.map` are these
   IDs.
3. Assign each group of `roles.map` to the enterprise application.

In the user pool:

1. Add a custom attribute `groups` (a string, mutable, at most 2048
   characters). The user pool calls it `custom:groups`. A mutable
   attribute lets the user pool change it at each sign-in.
2. Map the attribute of the SAML assertion
   `http://schemas.microsoft.com/ws/2008/06/identity/claims/groups` to
   `custom:groups`.
3. Give the app client the right to read `custom:groups`, so that the ID
   token has it.

The user pool puts the values of a SAML attribute with more than one
value in one text, in the form `[id1, id2]`. The apps also accept a list
and the forms `id1,id2` and `id1`. The apps give the user the first role
of `roles.map`, in the order of the definition, whose group is in the
claim. Without such a group, the user gets `default_role`. Without
`default_role`, the apps refuse the sign-in, and the sign-in page tells
the user to ask an administrator.

The groups of the user pool itself are in the claim `cognito:groups`.
Use `claim: "cognito:groups"` to give the roles from these groups in
place of the groups of Entra ID.

## Limits

- A sign-in that starts at Entra ID (for example from the My Apps
  portal) does not work: it comes to the app without the `state` of the
  flow, and the app refuses it.
- The sign-out of the app ends only the session of the app. The session
  at the user pool stays, so the next sign-in can go through without a
  password.

## Checks without a user pool

The checks of the repository do not call a real user pool. The mock
provider `scripts/mock_oidc.py` also acts as a user pool with the SAML
provider `EntraID`: its issuer has the path of a user pool, its
endpoints are on another origin, it refuses an authorization request
without `identity_provider`, and its ID tokens have
`email_verified: "false"`. The mock parameter `groups` of the
authorization request gives the groups of the user, in the claim
`custom:groups` as the text `[a, b]`. `scripts/check_provider_sign_in.py`
(the FastAPI app) and `scripts/auth_ui_test.py` (the Next.js app, and the
React app with the FastAPI app) sign in to
`tests/fixtures/cognito-sign-in.yaml` through it: one user with a group
of each role in turn, and then without a group.
