resource "aws_iam_role" "gateway" {
  count = local.auth_enabled ? 1 : 0
  name  = "${var.name_prefix}-gateway"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Principal = { Service = "bedrock-agentcore.amazonaws.com" }, Action = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
        ArnLike      = { "aws:SourceArn" = "${local.agentcore_arn}:gateway/*" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "gateway" {
  count = local.auth_enabled ? 1 : 0
  role  = aws_iam_role.gateway[0].id
  name  = "github-identity"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # User-delegated target calls use the JWT-specific API; administrator
        # discovery also needs the non-user token API. Never grant ForUserId.
        Effect   = "Allow", Action = ["bedrock-agentcore:GetWorkloadAccessToken", "bedrock-agentcore:GetWorkloadAccessTokenForJWT"]
        Resource = ["${local.agentcore_arn}:workload-identity-directory/default", "${local.agentcore_arn}:workload-identity-directory/default/workload-identity/${local.gateway_name}-*"]
      },
      {
        Effect = "Allow", Action = ["bedrock-agentcore:GetResourceOauth2Token"]
        # Token retrieval authorizes all four resource types, not just the provider.
        Resource = [
          aws_bedrockagentcore_oauth2_credential_provider.github[0].credential_provider_arn,
          "${local.agentcore_arn}:token-vault/default",
          "${local.agentcore_arn}:workload-identity-directory/default",
          "${local.agentcore_arn}:workload-identity-directory/default/workload-identity/${local.gateway_name}-*"
        ]
      },
      {
        Effect   = "Allow", Action = ["secretsmanager:GetSecretValue"]
        Resource = [aws_bedrockagentcore_oauth2_credential_provider.github[0].client_secret_arn[0].secret_arn]
      }
    ]
  })
}

resource "aws_iam_role" "portal" {
  count = local.auth_enabled ? 1 : 0
  name  = "${var.name_prefix}-consent"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Principal = { Service = "bedrock-agentcore.amazonaws.com" }, Action = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
        # ID is unavailable until creation; bootstrap is limited to portals in
        # this account/region. The workaround narrows it to the exact portal ARN.
        ArnLike = { "aws:SourceArn" = "${local.agentcore_arn}:consent-portal/*" }
      }
    }]
  })
  lifecycle {
    ignore_changes = [assume_role_policy]
  }
}

resource "aws_iam_role_policy" "portal" {
  count = local.auth_enabled ? 1 : 0
  role  = aws_iam_role.portal[0].id
  name  = "consent-identity"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow", Action = ["bedrock-agentcore:GetGateway", "bedrock-agentcore:GetGatewayTarget", "bedrock-agentcore:ListGatewayTargets"]
        Resource = [aws_bedrockagentcore_gateway.tools[0].gateway_arn, "${aws_bedrockagentcore_gateway.tools[0].gateway_arn}/target/*"]
      },
      {
        Effect = "Allow", Action = ["bedrock-agentcore:GetOauth2CredentialProvider"]
        # AWS authorizes provider reads against both the provider and its vault.
        # Omitting the vault causes portal /login to fail before IdP redirection.
        Resource = [
          "${local.agentcore_arn}:token-vault/default",
          aws_bedrockagentcore_oauth2_credential_provider.github[0].credential_provider_arn,
          aws_bedrockagentcore_oauth2_credential_provider.portal_login[0].credential_provider_arn
        ]
      },
      {
        # List API has no resource identifier; the documented portal role needs
        # this action. Limit the request to the selected region.
        Effect    = "Allow", Action = ["bedrock-agentcore:ListOauth2CredentialProviders"], Resource = "*"
        Condition = { StringEquals = { "aws:RequestedRegion" = var.aws_region } }
      },
      {
        # Session binding has no resource ARN in its request. AWS's documented
        # portal execution policy specifies '*' for this session-bound API.
        Effect    = "Allow", Action = ["bedrock-agentcore:CompleteResourceTokenAuth"], Resource = "*"
        Condition = { StringEquals = { "aws:RequestedRegion" = var.aws_region } }
      },
      {
        Effect = "Allow", Action = ["bedrock-agentcore:GetResourceOauth2Token"]
        Resource = [
          aws_bedrockagentcore_oauth2_credential_provider.portal_login[0].credential_provider_arn,
          aws_bedrockagentcore_oauth2_credential_provider.github[0].credential_provider_arn,
          "${local.agentcore_arn}:token-vault/default",
          "${local.agentcore_arn}:workload-identity-directory/default",
          "${local.agentcore_arn}:workload-identity-directory/default/workload-identity/${aws_bedrockagentcore_gateway.tools[0].gateway_id}"
        ]
      },
      {
        # The portal retrieves tokens for its attached Gateway workload only.
        Effect   = "Allow", Action = ["bedrock-agentcore:GetWorkloadAccessTokenForJWT"]
        Resource = ["${local.agentcore_arn}:workload-identity-directory/default", "${local.agentcore_arn}:workload-identity-directory/default/workload-identity/${aws_bedrockagentcore_gateway.tools[0].gateway_id}"]
      },
      {
        Effect   = "Allow", Action = ["secretsmanager:GetSecretValue"]
        Resource = [aws_bedrockagentcore_oauth2_credential_provider.portal_login[0].client_secret_arn[0].secret_arn, aws_bedrockagentcore_oauth2_credential_provider.github[0].client_secret_arn[0].secret_arn]
      }
    ]
  })
}
