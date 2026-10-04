resource "aws_iam_role" "runtime" {
  count = local.harness_enabled ? 1 : 0
  name  = "${var.name_prefix}-runtime"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Principal = { Service = "bedrock-agentcore.amazonaws.com" }, Action = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
        ArnLike      = { "aws:SourceArn" = "${local.agentcore_arn}:runtime/*" }
      }
    }]
  })
}
resource "aws_iam_role_policy" "runtime" {
  count = local.harness_enabled ? 1 : 0
  role  = aws_iam_role.runtime[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], Resource = local.runtime_model_resources },
      # ECR authentication has no resource ARN; image reads are repository scoped.
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"], Resource = [aws_ecr_repository.harness[0].arn] },
      # Runtime log names contain its service-assigned ID, unavailable before
      # creation. Scope to this account/region and the agent runtime name prefix.
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:DescribeLogStreams", "logs:PutResourcePolicy"], Resource = ["arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/${replace(var.name_prefix, "-", "_")}_harness-*", "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/${replace(var.name_prefix, "-", "_")}_harness-*:*"] },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/${replace(var.name_prefix, "-", "_")}_harness-*:log-stream:*"] },
      { Effect = "Allow", Action = ["logs:DescribeLogGroups"], Resource = ["arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:*"] }
    ]
  })

}
resource "aws_bedrockagentcore_agent_runtime" "harness" {
  count              = local.runtime_enabled ? 1 : 0
  agent_runtime_name = "${replace(var.name_prefix, "-", "_")}_harness"
  role_arn           = aws_iam_role.runtime[0].arn
  agent_runtime_artifact {
    container_configuration { container_uri = var.runtime_image_uri }
  }
  network_configuration {
    network_mode = "VPC"
    network_mode_config {
      subnets         = aws_subnet.private[*].id
      security_groups = [aws_security_group.runtime[0].id]
    }
  }
  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url   = local.discovery_url
      allowed_clients = [aws_cognito_user_pool_client.agent[0].id]
    }
  }
  request_header_configuration { request_header_allowlist = ["Authorization"] }
  protocol_configuration { server_protocol = "HTTP" }
  lifecycle_configuration {
    idle_runtime_session_timeout = 900
    max_lifetime                 = var.harness_timeout_seconds + 300
  }
  environment_variables = {
    OPENCODE_MODEL_ID       = var.opencode_model_id
    AWS_REGION              = var.aws_region
    GATEWAY_URL             = aws_bedrockagentcore_gateway.tools[0].gateway_url
    TARGET_REPO             = var.target_repo
    HARNESS_TIMEOUT_SECONDS = tostring(var.harness_timeout_seconds)
    HARNESS_MAX_STEPS       = tostring(var.harness_max_steps)
  }
  depends_on = [aws_iam_role_policy.runtime, aws_vpc_endpoint.interfaces, aws_vpc_endpoint.s3, time_sleep.eni_drain]
  lifecycle {
    precondition {
      condition     = startswith(var.runtime_image_uri, "${aws_ecr_repository.harness[0].repository_url}@sha256:")
      error_message = "The runtime image must belong to the dedicated harness ECR repository."
    }
  }
}
resource "aws_bedrockagentcore_agent_runtime_endpoint" "demo" {
  count                 = local.runtime_enabled ? 1 : 0
  name                  = "demo"
  agent_runtime_id      = aws_bedrockagentcore_agent_runtime.harness[0].agent_runtime_id
  agent_runtime_version = aws_bedrockagentcore_agent_runtime.harness[0].agent_runtime_version
}

# Runtime is deleted first; hold private network resources for ENI release.
# This is a bounded grace period, not proof that AWS released every ENI.
resource "time_sleep" "eni_drain" {
  count            = local.harness_enabled ? 1 : 0
  destroy_duration = "120s"
  depends_on       = [aws_subnet.private, aws_security_group.runtime, aws_vpc_endpoint.interfaces, aws_vpc_endpoint.s3]
}
