data "aws_bedrock_inference_profile" "coding" {
  count                = startswith(var.opencode_model_id, "us.") ? 1 : 0
  inference_profile_id = var.opencode_model_id
}

locals {
  runtime_model_resources = startswith(var.opencode_model_id, "us.") ? concat(
    [data.aws_bedrock_inference_profile.coding[0].inference_profile_arn],
    [for model in data.aws_bedrock_inference_profile.coding[0].models : model.model_arn]
  ) : ["arn:${data.aws_partition.current.partition}:bedrock:${var.aws_region}::foundation-model/${var.opencode_model_id}"]
}
