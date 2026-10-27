Make an internal IT help desk for our company. The staff sign in with
their work Microsoft account: our Entra ID is connected to the Amazon
Cognito user pool eu-west-1_Hd7Qm2xYz in eu-west-1, and its identity
provider there has the name EntraID. Nobody needs another password for
the help desk. The staff report problems as tickets, and the IT team
works on them. The IT team also sees the open issues of the Jira
project IT. The OpenAPI document of Jira is jira.openapi.json in this
folder, and the app calls Jira with the email address and an API token
of our Jira bot account.
