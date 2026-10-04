# Provider gap: AWS 6.67.x has no consent portal resource. See issue #49882:
# https://github.com/hashicorp/terraform-provider-aws/issues/49882
# No secret/client-secret/token is passed to local-exec or the external query.
resource "terraform_data" "consent_portal" {
  count = local.auth_enabled ? 1 : 0
  input = local.portal_config

  provisioner "local-exec" {
    command     = "python3 ../scripts/consent_portal.py upsert"
    environment = { PORTAL_CONFIG = jsonencode(self.input) }
  }
  provisioner "local-exec" {
    when        = destroy
    command     = "python3 ../scripts/consent_portal.py delete"
    environment = { PORTAL_CONFIG = jsonencode(self.input) }
  }
  depends_on = [aws_iam_role_policy.portal]
}

# Reconcile updates without deleting the portal or its user consent on every
# config change. The separate lifetime resource owns deletion on destroy.
resource "terraform_data" "consent_portal_config" {
  count            = local.auth_enabled ? 1 : 0
  triggers_replace = [sha256(jsonencode(local.portal_config))]
  input            = local.portal_config
  provisioner "local-exec" {
    command     = "python3 ../scripts/consent_portal.py upsert"
    environment = { PORTAL_CONFIG = jsonencode(self.input) }
  }
  depends_on = [terraform_data.consent_portal]
}

data "external" "consent_portal" {
  count   = local.auth_enabled ? 1 : 0
  program = ["python3", "${path.module}/../scripts/consent_portal.py", "read"]
  query = {
    name   = local.portal_config.name
    region = var.aws_region
  }
  depends_on = [terraform_data.consent_portal_config]
}
