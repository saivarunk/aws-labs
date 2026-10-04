resource "aws_cognito_user_pool" "demo" {
  count = local.auth_enabled ? 1 : 0
  name  = "${var.name_prefix}-users"

  admin_create_user_config {
    allow_admin_create_user_only = true
  }
  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }
}

resource "aws_cognito_user_pool_domain" "demo" {
  count        = local.auth_enabled ? 1 : 0
  domain       = "${var.name_prefix}-${data.aws_caller_identity.current.account_id}"
  user_pool_id = aws_cognito_user_pool.demo[0].id
}

resource "aws_cognito_user_pool_client" "agent" {
  count                                = local.auth_enabled ? 1 : 0
  name                                 = "agent-app"
  user_pool_id                         = aws_cognito_user_pool.demo[0].id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = [var.login_callback_url]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  access_token_validity                = 60
  id_token_validity                    = 60
  token_validity_units {
    access_token = "minutes"
    id_token     = "minutes"
  }
}

resource "aws_cognito_user_pool_client" "rogue" {
  count                                = local.auth_enabled ? 1 : 0
  name                                 = "rogue-app"
  user_pool_id                         = aws_cognito_user_pool.demo[0].id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = [var.login_callback_url]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
}

resource "aws_cognito_user_pool_client" "portal" {
  count                                = local.auth_enabled ? 1 : 0
  name                                 = "consent-portal"
  user_pool_id                         = aws_cognito_user_pool.demo[0].id
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["https://localhost.invalid/callback"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true

  # The portal URL depends on this client's credential provider. The narrow
  # consent_portal.py workaround owns callbacks after portal creation and
  # updates the full client configuration without logging its client secret.
  lifecycle {
    ignore_changes = [callback_urls]
  }
}

resource "aws_cognito_user" "test" {
  for_each       = local.auth_enabled ? toset(["user-a", "user-b"]) : toset([])
  user_pool_id   = aws_cognito_user_pool.demo[0].id
  username       = each.value
  message_action = "SUPPRESS"
  # AWS generates a temporary password. Set a permanent password locally using
  # scripts/set_user_password.py; no password is output or hardcoded here.
}
