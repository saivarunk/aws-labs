resource "aws_ecr_repository" "harness" {
  count                = local.harness_enabled ? 1 : 0
  name                 = "${var.name_prefix}-harness"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true # Demo cleanup intentionally removes built images.
  image_scanning_configuration { scan_on_push = true }
}
resource "aws_s3_bucket" "build" {
  count         = local.harness_enabled ? 1 : 0
  bucket_prefix = "${var.name_prefix}-build-"
  force_destroy = true # Only curated, secret-free source archives belong here.
}
resource "aws_s3_bucket_public_access_block" "build" {
  count                   = local.harness_enabled ? 1 : 0
  bucket                  = aws_s3_bucket.build[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "build" {
  count  = local.harness_enabled ? 1 : 0
  bucket = aws_s3_bucket.build[0].id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_cloudwatch_log_group" "build" {
  count             = local.harness_enabled ? 1 : 0
  name              = "/aws/codebuild/${var.name_prefix}-harness"
  retention_in_days = var.log_retention_days
}
resource "aws_iam_role" "build" {
  count = local.harness_enabled ? 1 : 0
  name  = "${var.name_prefix}-build"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "codebuild.amazonaws.com" }, Action = "sts:AssumeRole", Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id } } }]
  })
}
resource "aws_iam_role_policy" "build" {
  count = local.harness_enabled ? 1 : 0
  role  = aws_iam_role.build[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = ["${aws_s3_bucket.build[0].arn}/source/*"] },
      { Effect = "Allow", Action = ["s3:GetBucketLocation", "s3:GetBucketAcl"], Resource = [aws_s3_bucket.build[0].arn] },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["${aws_cloudwatch_log_group.build[0].arn}:*"] },
      # ECR login has no resource-level permission.
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], Resource = [aws_ecr_repository.harness[0].arn] }
    ]
  })
}
resource "aws_codebuild_project" "harness" {
  count         = local.harness_enabled ? 1 : 0
  name          = "${var.name_prefix}-harness"
  service_role  = aws_iam_role.build[0].arn
  build_timeout = 30
  artifacts { type = "NO_ARTIFACTS" }
  source {
    type      = "S3"
    location  = "${aws_s3_bucket.build[0].bucket}/source/bootstrap.zip"
    buildspec = "harness/buildspec.yml"
  }
  environment {
    type            = "ARM_CONTAINER"
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/amazonlinux-aarch64-standard:3.0"
    privileged_mode = true # Image building only; Runtime never runs Docker.
    environment_variable {
      name  = "ECR_REPOSITORY_URL"
      value = aws_ecr_repository.harness[0].repository_url
    }
  }
  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.build[0].name
    }
  }
  depends_on = [aws_iam_role_policy.build]
}
