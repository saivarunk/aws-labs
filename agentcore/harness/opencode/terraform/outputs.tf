output "github_oauth_callback_url" {
  description = "Copy this exact URL into GitHub OAuth App's Authorization callback URL."
  value       = one(aws_bedrockagentcore_oauth2_credential_provider.github[*].callback_url)
}

output "github_credential_provider_arn" {
  description = "Provider ARN for outbound Gateway OAuth, never a GitHub access token."
  value       = one(aws_bedrockagentcore_oauth2_credential_provider.github[*].credential_provider_arn)
}

output "consent_portal_url" {
  description = "Open this URL to sign in with Cognito and connect GitHub."
  value       = local.auth_enabled ? data.external.consent_portal[0].result.portal_url : null
}

output "cognito_user_pool_id" {
  value = local.auth_enabled ? aws_cognito_user_pool.demo[0].id : null
}

output "agent_app_client_id" {
  value = local.auth_enabled ? aws_cognito_user_pool_client.agent[0].id : null
}

output "rogue_app_client_id" {
  value = local.auth_enabled ? aws_cognito_user_pool_client.rogue[0].id : null
}

output "gateway_url" {
  value = local.auth_enabled ? aws_bedrockagentcore_gateway.tools[0].gateway_url : null
}

output "build_config" {
  value = local.harness_enabled ? {
    region         = var.aws_region
    bucket         = aws_s3_bucket.build[0].bucket
    project        = aws_codebuild_project.harness[0].name
    repository     = aws_ecr_repository.harness[0].name
    repository_url = aws_ecr_repository.harness[0].repository_url
  } : null
}
output "runtime_arn" {
  value = local.runtime_enabled ? aws_bedrockagentcore_agent_runtime.harness[0].agent_runtime_arn : null
}
output "private_network" {
  value = local.harness_enabled ? {
    vpc_id              = aws_vpc.harness[0].id
    subnets             = aws_subnet.private[*].id
    runtime_sg          = aws_security_group.runtime[0].id
    endpoint_sg         = aws_security_group.endpoints[0].id
    private_route_table = aws_route_table.private[0].id
  } : null
}
output "login_config" {
  value = local.auth_enabled ? {
    authorization_url = "https://${aws_cognito_user_pool_domain.demo[0].domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/authorize"
    token_url         = "https://${aws_cognito_user_pool_domain.demo[0].domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/token"
    callback_url      = var.login_callback_url
    agent_client_id   = aws_cognito_user_pool_client.agent[0].id
    rogue_client_id   = aws_cognito_user_pool_client.rogue[0].id
    region            = var.aws_region
  } : null
}
output "harness_model" {
  value = {
    engine    = "opencode"
    model_id  = var.opencode_model_id
    resources = local.runtime_model_resources
  }
}
