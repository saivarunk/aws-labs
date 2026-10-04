# Security boundaries

This example protects GitHub credentials, OAuth client secrets, Cognito access
tokens, source repositories, the runtime role, local state, and agent logs.

## Controls

| Boundary | Control |
| --- | --- |
| Client → Runtime | Cognito access token; only the agent client is accepted |
| User → managed portal | Cognito sign-in and user-specific GitHub consent |
| Runtime → Gateway | Forwarded caller JWT; agent and portal clients accepted, rogue client excluded |
| Gateway → GitHub | Identity-managed OAuth credentials; no PAT in the harness |
| OpenCode → Gateway | Loopback proxy; exact repository/session branch, five approved tools |
| Workspace → push | Deliverables match local files; independent format/vet/race/coverage gates |
| Push → PR | One confirmed push before creating the PR; confirmed tool URL before completion |
| Runtime → AWS | Private endpoint-only egress and scoped execution-role IAM |
| Invocation → files/process | Temporary workspace/HOME/configuration, process-group termination, bounded output/time/steps |
| Agent output → logs | Caller-token and credential-format redaction; large-event chunking |
| Source → build | Explicit source archive allowlist; no local state, configuration, or tokens |

Runtime and Gateway authorizers serve different purposes. Gateway accepts the
portal client to validate portal sign-in; Runtime accepts only the agent client.
The Gateway VPC endpoint uses a wildcard principal for JWT traffic, constrained
by Gateway ARN and authorizer. The Bedrock endpoint names the runtime role and
selected model resources. Private outbound networking does not make the inbound
Runtime API accessible only from this VPC.

## Limits

Generated Go tests are arbitrary code running as the harness OS user. They can
access execution-role credentials and may inspect other process data available
to that user. The MCP proxy, prompts, and OpenCode shell rules are defense in
depth, not an isolation boundary against malicious generated code. Network
restrictions and IAM remain necessary.

The OAuth `repo` scope also grants private-repository access. The configured
repository policy does not narrow the provider's OAuth grant. A GitHub App can
provide a narrower repository installation boundary, but its interoperability
is outside this example.

Kimi's US profile routes inference within the US; it does not guarantee
processing solely in us-east-1. Terraform includes the discovered profile and
foundation-model ARNs in IAM and the Bedrock endpoint policy.

State and saved plans contain plaintext OAuth secrets. Gitignore prevents
accidental addition, not access to files already tracked or stored elsewhere.
No remote encrypted backend, high availability, or production hardening is
included. Agent logs include specifications and generated source even after
credential redaction; restrict access to those logs.

## What has been checked

Local tests cover policy rejection, MCP behavior, credential redaction, process
cleanup, task configuration, and packaging. The baseline deployment passed
private model invocation, missing/rogue JWT rejection, an unconsented GitHub
attempt, and a user-consented push/PR. Full cross-user write isolation,
cross-session isolation, and a clean apply–demo–destroy cycle still need broader
end-to-end validation. Run the supplied live checks for your own deployment.
