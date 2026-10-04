data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  auth_enabled  = var.enable_managed_portal
  agentcore_arn = "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}"
  gateway_name  = "${var.name_prefix}-gateway"
  discovery_url = local.auth_enabled ? "https://${aws_cognito_user_pool.demo[0].endpoint}/.well-known/openid-configuration" : null
  portal_config = local.auth_enabled ? {
    name             = "${var.name_prefix}-consent"
    region           = var.aws_region
    executionRoleArn = aws_iam_role.portal[0].arn
    idpConfig = {
      credentialProviderArn = aws_bedrockagentcore_oauth2_credential_provider.portal_login[0].credential_provider_arn
      scopes                = ["openid", "email", "profile"]
    }
    sources     = [{ identifier = aws_bedrockagentcore_gateway.tools[0].gateway_id, type = "agentcore-gateway" }]
    description = "User GitHub connections for the coding harness"
    tags        = merge(var.tags, { Project = var.name_prefix, ManagedBy = "Terraform" })
    pool_id     = aws_cognito_user_pool.demo[0].id
    client_id   = aws_cognito_user_pool_client.portal[0].id
  } : null
}
