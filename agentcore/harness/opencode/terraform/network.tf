locals {
  harness_enabled = var.enable_harness
  runtime_enabled = var.enable_harness && var.runtime_image_uri != null
  private_azs     = ["use1-az1", "use1-az2"]
  endpoint_services = local.harness_enabled ? toset([
    "bedrock-runtime", "ecr.api", "ecr.dkr", "logs", "bedrock-agentcore.gateway"
  ]) : toset([])
}
resource "aws_vpc" "harness" {
  count                = local.harness_enabled ? 1 : 0
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${var.name_prefix}-private" }
  lifecycle {
    precondition {
      condition     = var.aws_region == "us-east-1" && local.auth_enabled && !var.enable_nat
      error_message = "This verified topology requires us-east-1, managed auth, and enable_nat=false. NAT fallback is not implemented."
    }
  }
}
resource "aws_subnet" "private" {
  count                   = local.harness_enabled ? 2 : 0
  vpc_id                  = aws_vpc.harness[0].id
  availability_zone_id    = local.private_azs[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.name_prefix}-private-${count.index}" }
}
resource "aws_route_table" "private" {
  count  = local.harness_enabled ? 1 : 0
  vpc_id = aws_vpc.harness[0].id
  # No default route, IGW, or NAT. S3 adds only its managed prefix-list route.
}
resource "aws_route_table_association" "private" {
  count          = local.harness_enabled ? 2 : 0
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[0].id
}
resource "aws_security_group" "runtime" {
  count       = local.harness_enabled ? 1 : 0
  name        = "${var.name_prefix}-runtime"
  description = "Runtime: HTTPS to endpoints only"
  vpc_id      = aws_vpc.harness[0].id
}
resource "aws_security_group" "endpoints" {
  count       = local.harness_enabled ? 1 : 0
  name        = "${var.name_prefix}-endpoints"
  description = "PrivateLink: HTTPS from runtime only"
  vpc_id      = aws_vpc.harness[0].id
}
resource "aws_vpc_security_group_egress_rule" "endpoints" {
  count                        = local.harness_enabled ? 1 : 0
  security_group_id            = aws_security_group.runtime[0].id
  referenced_security_group_id = aws_security_group.endpoints[0].id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
resource "aws_vpc_security_group_ingress_rule" "endpoints" {
  count                        = local.harness_enabled ? 1 : 0
  security_group_id            = aws_security_group.endpoints[0].id
  referenced_security_group_id = aws_security_group.runtime[0].id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
resource "aws_vpc_endpoint" "interfaces" {
  for_each            = local.endpoint_services
  vpc_id              = aws_vpc.harness[0].id
  service_name        = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoints[0].id]
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [merge({
      Effect = "Allow"
      # JWT callers have no IAM principal. Gateway requires Principal '*', but
      # its allowed actions and exact Gateway ARN still constrain this endpoint.
      Principal = "*"
      Action = each.key == "bedrock-agentcore.gateway" ? ["bedrock-agentcore:InvokeGateway"] : (
        each.key == "bedrock-runtime" ? ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"] : (
          startswith(each.key, "ecr.") ? ["ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"] : ["logs:CreateLogStream", "logs:PutLogEvents"]
        )
      )
      Resource = each.key == "bedrock-agentcore.gateway" ? [aws_bedrockagentcore_gateway.tools[0].gateway_arn] : (
        each.key == "bedrock-runtime" ? local.runtime_model_resources : ["*"]
      )
      # ECR GetAuthorizationToken requires '*'; execution-role IAM restricts
      # repository reads and log writes. Account condition excludes other roles.
      Condition = contains(["bedrock-agentcore.gateway", "bedrock-runtime"], each.key) ? {} : { StringEquals = { "aws:PrincipalAccount" = data.aws_caller_identity.current.account_id } }
      }, each.key == "bedrock-runtime" ? {
      Principal = { AWS = aws_iam_role.runtime[0].arn }
    } : {})]
  })
}
resource "aws_vpc_endpoint" "s3" {
  count             = local.harness_enabled ? 1 : 0
  vpc_id            = aws_vpc.harness[0].id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private[0].id]
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Principal = "*", Action = ["s3:GetObject"]
      # ECR's regional starport bucket stores image layers under service keys.
      Resource = ["arn:${data.aws_partition.current.partition}:s3:::prod-${var.aws_region}-starport-layer-bucket/*"]
    }]
  })
}
resource "aws_vpc_security_group_egress_rule" "s3" {
  count             = local.harness_enabled ? 1 : 0
  security_group_id = aws_security_group.runtime[0].id
  prefix_list_id    = aws_vpc_endpoint.s3[0].prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
