terraform {
  required_version = ">= 1.7.0, < 2.0.0"

  # Intentionally local: OAuth secrets will be present in state once Identity
  # resources are enabled. State and plans must never be committed.
  backend "local" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.67.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.13.0"
    }
    external = {
      source  = "hashicorp/external"
      version = "~> 2.3.0"
    }
  }
}
