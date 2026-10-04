# Two-stage bootstrap: the GitHub App is created first with a temporary callback;
# then this resource returns the real callback to register in GitHub settings.
# This resource intentionally stores its client values in local Terraform state.
resource "aws_bedrockagentcore_oauth2_credential_provider" "github" {
  count = var.enable_github_identity ? 1 : 0

  name                       = "${var.name_prefix}-github"
  credential_provider_vendor = "GithubOauth2"

  oauth2_provider_config {
    github_oauth2_provider_config {
      client_id     = var.github_oauth_client_id
      client_secret = var.github_oauth_client_secret
    }
  }

  lifecycle {
    precondition {
      condition     = var.github_oauth_client_id != null && var.github_oauth_client_secret != null
      error_message = "Set both TF_VAR_github_oauth_client_id and TF_VAR_github_oauth_client_secret before enabling Identity."
    }
    precondition {
      condition     = var.github_oauth_client_id == null ? true : length(trimspace(var.github_oauth_client_id)) > 0
      error_message = "GitHub OAuth client ID cannot be empty."
    }
    precondition {
      condition     = var.github_oauth_client_secret == null ? true : length(trimspace(var.github_oauth_client_secret)) > 0
      error_message = "GitHub OAuth client secret cannot be empty."
    }
  }
}

resource "aws_bedrockagentcore_oauth2_credential_provider" "portal_login" {
  count                      = local.auth_enabled ? 1 : 0
  name                       = "${var.name_prefix}-portal-login"
  credential_provider_vendor = "CustomOauth2"

  oauth2_provider_config {
    custom_oauth2_provider_config {
      client_id                    = aws_cognito_user_pool_client.portal[0].id
      client_secret                = aws_cognito_user_pool_client.portal[0].client_secret
      client_authentication_method = "CLIENT_SECRET_BASIC"
      oauth_discovery {
        discovery_url = local.discovery_url
      }
    }
  }
  depends_on = [aws_cognito_user_pool_domain.demo]
}
