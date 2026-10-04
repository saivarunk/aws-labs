# Connect GitHub through the managed consent portal

Run these commands from `agentcore/harness/opencode`. Use the AWS profile and
local tfvars for this deployment throughout setup and cleanup.

## 1. Register an OAuth App

Open [GitHub → Settings → Developer settings → OAuth Apps → New OAuth App](https://github.com/settings/applications/new).

| Field | Suggested value |
| --- | --- |
| Application name | `AgentCore OpenCode demo` |
| Homepage URL | Your example repository URL |
| Description | User-delegated GitHub access for an AgentCore coding harness |
| Authorization callback URL | Temporarily use your HTTPS homepage; replace it with the AWS-generated callback in step 3 |

Register the app and generate a client secret. Store both values locally. The
temporary callback only allows app registration; do not authorize the app until
it has the exact Identity callback below.

## 2. Supply client values and provision Identity

If you have not done so, copy `terraform/terraform.tfvars.example` to
`terraform/terraform.tfvars`. Set your region, resource prefix, and application
repository, and set `enable_github_identity = true`.

In zsh, read the values without recording the secret in command history:

```zsh
read 'TF_VAR_github_oauth_client_id?GitHub Client ID: '
read -s 'TF_VAR_github_oauth_client_secret?GitHub Client Secret: '
print
export TF_VAR_github_oauth_client_id TF_VAR_github_oauth_client_secret
terraform -chdir=terraform init
terraform -chdir=terraform plan
terraform -chdir=terraform apply
```

Keep these variables set for later Terraform commands. The Identity provider
stores the client secret in local Terraform state. State, saved plans, and local
tfvars must remain private; `sensitive` hides normal display but does not encrypt
state. Client values are not embedded in the container or runtime environment.

## 3. Update the GitHub callback

```sh
terraform -chdir=terraform output -raw github_oauth_callback_url
```

Set the OAuth App's **Authorization callback URL** to that exact output and save.
Do not guess the URL from the app name or region.

There are three different callbacks in this setup:

| Callback | Purpose |
| --- | --- |
| AWS-generated `github_oauth_callback_url` | GitHub OAuth App → AgentCore Identity |
| `PORTAL_URL/callback` | Cognito → managed portal sign-in |
| `PORTAL_URL/connect/callback` | Return to the managed portal after user connection |

The portal adapter manages its Cognito callback. Only the first URL goes into
the GitHub OAuth App. The CLI uses a separate loopback callback at
`http://localhost:8765/callback`.

## 4. Enable the portal and target

Set `enable_managed_portal = true`, then plan and apply. Set a password for the
pre-created Cognito user and open the portal:

```sh
python3 -m scripts.set_user_password --user user-a
terraform -chdir=terraform output -raw consent_portal_url
```

Sign in as `user-a`. Next set `enable_github_target = true` and apply again.
The target's five schemas are checked in at `terraform/github-tools.json`.
Schema-upfront configuration avoids separate administrator discovery consent;
each user still needs to connect GitHub before calling its tools. Wait for the
target to become **READY**.

## 5. Approve your GitHub connection

Return to the portal as `user-a`, choose **Connect** for GitHub, and approve the
OAuth App. The connection should show **Connected**. If the target list is
stale, refresh it and allow a few minutes for metadata caching.

This example requests `repo`: the hosted MCP check used this scope even for a
public target. It also grants access to private repositories available to your
GitHub user. `target_repo` is enforced by the harness, not by the OAuth grant.
A separate test GitHub account can reduce the grant's impact. Organization
repositories may require OAuth App approval and SSO authorization.

After deploying the runtime, use the same Cognito identity for the CLI:

```sh
python3 -m scripts.login
python3 -m scripts.verify.github --expected-login YOUR_GITHUB_USERNAME
```

The check reads identity and repository information through Gateway. It does
not retrieve a GitHub access token or push code. Return to the
[README](../README.md) to run the coding demo.

## Troubleshooting

- **Portal sign-in error:** check that the Cognito portal client callback matches
  `PORTAL_URL/callback`. The adapter configures this; avoid manually substituting
  the GitHub callback.
- **No targets:** enable the GitHub target, apply, and check that it is READY.
- **GitHub read rejected:** reconnect as the same Cognito user used for CLI
  login, confirm the `repo` grant, and check organization restrictions.
- **Expired CLI token:** run the login helper again. Never paste a token or a
  callback URL containing authorization parameters into an issue.

The Terraform-managed CLI adapter is limited to the consent portal provider gap
and Cognito callback reconciliation. Tool schemas should be reviewed and
updated when the upstream hosted MCP API changes; automatic sync is disabled.

## Cleanup

Use the same local configuration to destroy AWS resources. Separately revoke
GitHub authorization and remove the OAuth App if no longer needed. Then unset
both `TF_VAR_github_oauth_client_*` variables.
