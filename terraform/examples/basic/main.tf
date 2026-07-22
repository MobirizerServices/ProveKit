terraform {
  required_providers {
    provekit = {
      source = "provekit/provekit"
    }
  }
}

# With dev_overrides in place (see ../../README.md) there is no `terraform init` step and no
# version constraint to satisfy — Terraform execs your local binary directly.
provider "provekit" {
  endpoint = "http://localhost:8000"
  # email / password come from PROVEKIT_EMAIL and PROVEKIT_PASSWORD.
  # On an instance running with HOSTED=false, leave them unset entirely.
}

resource "provekit_project" "checkout_agent" {
  name       = "checkout-agent"
  retention  = 30
  redact_pii = true
}

# The plaintext key exists only in the create response, so it lands in Terraform state and
# nowhere else. Treat the state file accordingly.
resource "provekit_api_key" "ci" {
  project_id = provekit_project.checkout_agent.id
  name       = "ci"
}

resource "provekit_alert" "error_rate" {
  project_id   = provekit_project.checkout_agent.id
  name         = "checkout error rate"
  metric       = "error_rate"
  comparator   = "gt"
  threshold    = 0.05
  window_hours = 1
  email        = "oncall@example.com"
}

resource "provekit_alert" "p95_latency" {
  project_id   = provekit_project.checkout_agent.id
  metric       = "latency_p95_ms"
  threshold    = 8000
  window_hours = 6
  webhook_url  = "https://hooks.example.com/provekit"
}

output "ingest_key" {
  value     = provekit_api_key.ci.key
  sensitive = true
}
