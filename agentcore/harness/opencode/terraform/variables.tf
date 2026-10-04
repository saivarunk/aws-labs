variable "aws_region" {
  description = "AWS deployment region; must pass the regional AgentCore preflight."
  type        = string
  validation {
    condition     = can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]+$", var.aws_region))
    error_message = "Set an explicit AWS region."
  }
}

variable "name_prefix" {
  description = "Short lowercase resource prefix."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,23}$", var.name_prefix))
    error_message = "Use 3–24 lowercase letters, digits, or hyphens, starting with a letter."
  }
}

variable "vpc_cidr" {
  description = "Private IPv4 range for the demo VPC."
  type        = string
  default     = "10.42.0.0/16"
  validation {
    condition     = can(cidrsubnet(var.vpc_cidr, 4, 3)) && !strcontains(var.vpc_cidr, ":")
    error_message = "Use an IPv4 CIDR with room for at least four subnets."
  }
}

variable "enable_nat" {
  description = "Optional NAT fallback. Default deployment must work without it."
  type        = bool
  default     = false
}

variable "target_repo" {
  description = "Pre-created GitHub owner/repo with an initialized default branch."
  type        = string
  default     = null
  validation {
    condition     = var.target_repo == null ? true : can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.target_repo))
    error_message = "Use owner/repo, not a URL."
  }
}

variable "github_oauth_client_id" {
  description = "GitHub OAuth client ID, supplied through TF_VAR_github_oauth_client_id."
  type        = string
  sensitive   = true
  default     = null
}

variable "github_oauth_client_secret" {
  description = "GitHub OAuth client secret. Sensitive still means it is stored in local state."
  type        = string
  sensitive   = true
  default     = null
}

variable "enable_github_identity" {
  description = "Bootstrap switch: enable only after creating the GitHub OAuth App."
  type        = bool
  default     = false
}

variable "enable_managed_portal" {
  description = "Deploy Cognito, Gateway, and the managed consent portal after GitHub bootstrap."
  type        = bool
  default     = false
}

variable "enable_github_target" {
  description = "Add the GitHub MCP target after portal sign-in is ready; administrator discovery may require interactive consent."
  type        = bool
  default     = false
}

variable "github_oauth_scopes" {
  description = "Hosted MCP uses repo, which also grants private access. public_repo is narrower but currently fails hosted OAuth checks."
  type        = set(string)
  default     = ["repo"]
  validation {
    condition     = contains([toset(["public_repo"]), toset(["repo"])], var.github_oauth_scopes)
    error_message = "Choose either public_repo or repo; the hosted GitHub MCP OAuth checks currently require repo."
  }
}

variable "login_callback_url" {
  description = "Loopback redirect for the public PKCE CLI client (not the GitHub or portal callback)."
  type        = string
  default     = "http://localhost:8765/callback"
}

variable "log_retention_days" {
  description = "CloudWatch retention period."
  type        = number
  default     = 7
  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365], var.log_retention_days)
    error_message = "Choose a supported CloudWatch retention period."
  }
}

variable "tags" {
  description = "Additional resource tags."
  type        = map(string)
  default     = {}
}

variable "enable_harness" {
  description = "Create private networking and the ARM64 CodeBuild/ECR build infrastructure."
  type        = bool
  default     = false
}

variable "runtime_image_uri" {
  description = "Immutable ECR image URI from build_image.sh. Null stages infrastructure before Runtime creation."
  type        = string
  default     = null
  validation {
    condition     = var.runtime_image_uri == null ? true : can(regex("^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[^@]+@sha256:[a-f0-9]{64}$", var.runtime_image_uri))
    error_message = "Use an immutable ECR digest URI, not a mutable tag."
  }
}

variable "manage_runtime_logs" {
  description = "After Runtime creation, import its service-created log groups and apply retention."
  type        = bool
  default     = false
}

variable "opencode_model_id" {
  description = "Bedrock model or US inference profile used by OpenCode."
  type        = string
  default     = "us.moonshotai.kimi-k3"
  validation {
    condition     = contains(["us.moonshotai.kimi-k3", "qwen.qwen3-coder-30b-a3b-v1:0"], var.opencode_model_id)
    error_message = "Use the tested Kimi K3 US profile or Qwen3 Coder model."
  }
}

variable "harness_timeout_seconds" {
  description = "Wall-clock budget for one coding run."
  type        = number
  default     = 2700
  validation {
    condition     = var.harness_timeout_seconds >= 60 && var.harness_timeout_seconds <= 7200 && floor(var.harness_timeout_seconds) == var.harness_timeout_seconds
    error_message = "Use an integer timeout between 60 and 7200 seconds."
  }
}

variable "harness_max_steps" {
  description = "Maximum OpenCode model steps per coding run."
  type        = number
  default     = 180
  validation {
    condition     = var.harness_max_steps >= 1 && var.harness_max_steps <= 300 && floor(var.harness_max_steps) == var.harness_max_steps
    error_message = "Use an integer step limit between 1 and 300."
  }
}
