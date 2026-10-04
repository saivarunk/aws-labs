locals {
  runtime_log_qualifiers = local.runtime_enabled && var.manage_runtime_logs ? toset(["DEFAULT", "demo"]) : toset([])
}
# AWS creates these log groups during provisioning. Stage this after Runtime
# is READY so the service-assigned runtime ID is known to declarative import.
import {
  for_each = local.runtime_log_qualifiers
  to       = aws_cloudwatch_log_group.runtime[each.value]
  id       = "/aws/bedrock-agentcore/runtimes/${aws_bedrockagentcore_agent_runtime.harness[0].agent_runtime_id}-${each.value}"
}
resource "aws_cloudwatch_log_group" "runtime" {
  for_each          = local.runtime_log_qualifiers
  name              = "/aws/bedrock-agentcore/runtimes/${aws_bedrockagentcore_agent_runtime.harness[0].agent_runtime_id}-${each.value}"
  retention_in_days = var.log_retention_days
}

# Gateway logs expose downstream OAuth failures that MCP intentionally masks.
# Vended delivery stays in native Terraform; no diagnostic console resources.
resource "aws_cloudwatch_log_group" "gateway" {
  count             = local.auth_enabled ? 1 : 0
  name              = "/aws/vendedlogs/bedrock-agentcore/gateway/APPLICATION_LOGS/${aws_bedrockagentcore_gateway.tools[0].gateway_id}"
  retention_in_days = var.log_retention_days
}
resource "aws_cloudwatch_log_delivery_source" "gateway" {
  count        = local.auth_enabled ? 1 : 0
  name         = "${var.name_prefix}-gateway-logs"
  resource_arn = aws_bedrockagentcore_gateway.tools[0].gateway_arn
  log_type     = "APPLICATION_LOGS"
}
resource "aws_cloudwatch_log_delivery_destination" "gateway" {
  count         = local.auth_enabled ? 1 : 0
  name          = "${var.name_prefix}-gateway-logs"
  output_format = "json"
  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.gateway[0].arn
  }
}
resource "aws_cloudwatch_log_delivery" "gateway" {
  count                    = local.auth_enabled ? 1 : 0
  delivery_source_name     = aws_cloudwatch_log_delivery_source.gateway[0].name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.gateway[0].arn
}

locals {
  runtime_delivery_types = local.runtime_enabled ? toset(["APPLICATION_LOGS", "USAGE_LOGS"]) : toset([])
}
resource "aws_cloudwatch_log_group" "runtime_delivery" {
  for_each          = local.runtime_delivery_types
  name              = "/aws/vendedlogs/bedrock-agentcore/runtime/${each.key}/${aws_bedrockagentcore_agent_runtime.harness[0].agent_runtime_id}"
  retention_in_days = var.log_retention_days
}
resource "aws_cloudwatch_log_delivery_source" "runtime" {
  for_each     = local.runtime_delivery_types
  name         = "${var.name_prefix}-runtime-${lower(replace(each.key, "_", "-"))}"
  resource_arn = aws_bedrockagentcore_agent_runtime.harness[0].agent_runtime_arn
  log_type     = each.key
}
resource "aws_cloudwatch_log_delivery_destination" "runtime" {
  for_each      = local.runtime_delivery_types
  name          = "${var.name_prefix}-runtime-${lower(replace(each.key, "_", "-"))}"
  output_format = "json"
  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.runtime_delivery[each.key].arn
  }
}
resource "aws_cloudwatch_log_delivery" "runtime" {
  for_each                 = local.runtime_delivery_types
  delivery_source_name     = aws_cloudwatch_log_delivery_source.runtime[each.key].name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.runtime[each.key].arn
  # Service payload fields can include specifications and agent output. Keep
  # application delivery to request metadata; stdout carries redacted OpenCode events.
  record_fields = each.key == "APPLICATION_LOGS" ? ["resource_arn", "event_timestamp", "request_id", "session_id", "trace_id", "span_id", "service_name", "operation", "severityNumber", "severityText"] : ["resource_arn", "event_timestamp", "resource", "attributes", "metrics"]
}
