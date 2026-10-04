# Replace the screenshot placeholders

The SVG files are labeled placeholders, not captured AWS screens. Replace each
README image link with your reviewed PNG/JPEG, stored in this directory.

| Placeholder | Suggested capture |
| --- | --- |
| `consent-portal.svg` | Managed consent portal showing the GitHub provider/target as Connected |
| `runtime-startup.svg` | CloudWatch rows showing server_started, invocation_started, Gateway discovery, and the first agent step |
| `opencode-logs.svg` | One run's readable model messages and tool/command output in Logs Insights |
| `demo-result.svg` | Final confirmed PR summary and successful gate results |

Headless OpenCode JSON mode has no interactive intro banner. Use actual startup
and step events; do not add a decorative banner and present it as captured logs.

Crop browser address bars and unrelated UI. Remove account IDs, resource IDs,
user emails, authorization URLs/query strings, passwords, tokens, local paths,
and private repository/task contents. Redaction in the harness is not a promise
that every possible secret is removed. Inspect the final image at full size
before adding it to Git.
