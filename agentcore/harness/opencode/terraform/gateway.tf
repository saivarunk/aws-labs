resource "aws_bedrockagentcore_gateway" "tools" {
  count           = local.auth_enabled ? 1 : 0
  name            = local.gateway_name
  role_arn        = aws_iam_role.gateway[0].arn
  authorizer_type = "CUSTOM_JWT"
  protocol_type   = "MCP"
  protocol_configuration {
    mcp {
      supported_versions = ["2025-03-26", "2025-06-18", "2025-11-25"]
      session_configuration { session_timeout_in_seconds = 900 }
      streaming_configuration { enable_response_streaming = true }
    }
  }
  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url = local.discovery_url
      # Managed portal tokens must pass the same Gateway authorizer.
      # Runtime remains agent-app-only; rogue-app is deliberately excluded.
      allowed_clients = [aws_cognito_user_pool_client.agent[0].id, aws_cognito_user_pool_client.portal[0].id]
    }
  }
  depends_on = [aws_iam_role_policy.gateway]

  lifecycle {
    precondition {
      condition     = var.enable_github_identity && var.target_repo != null
      error_message = "Enable GitHub Identity and set target_repo before deploying the managed portal."
    }
  }
}

resource "aws_bedrockagentcore_gateway_target" "github" {
  count              = var.enable_github_target ? 1 : 0
  name               = "github"
  gateway_identifier = aws_bedrockagentcore_gateway.tools[0].gateway_id
  metadata_configuration {
    allowed_request_headers = ["Mcp-Param-owner", "Mcp-Param-repo"]
  }
  credential_provider_configuration {
    oauth {
      provider_arn       = aws_bedrockagentcore_oauth2_credential_provider.github[0].credential_provider_arn
      grant_type         = "AUTHORIZATION_CODE"
      default_return_url = "${data.external.consent_portal[0].result.portal_url}/connect/callback"
      scopes             = var.github_oauth_scopes
    }
  }
  target_configuration {
    mcp {
      mcp_server {
        endpoint     = "https://api.githubcopilot.com/mcp/"
        listing_mode = "DEFAULT"
        # Schemas captured from live GitHub discovery. This avoids a separate
        # administrator 3LO identity; per-user authorization still occurs at call time.
        mcp_tool_schema {
          inline_payload {
            payload = file("${path.module}/github-tools.json")
          }
        }
      }
    }
  }
  depends_on = [terraform_data.consent_portal_config]
}
