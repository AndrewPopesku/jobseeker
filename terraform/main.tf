terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "containerregistry.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Service account
# ---------------------------------------------------------------------------

data "google_compute_default_service_account" "default" {}

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

locals {
  secrets = {
    "jobseeker-telegram-bot-token"  = var.telegram_bot_token
    "jobseeker-telegram-user-id"    = var.telegram_user_id
    "jobseeker-google-api-key"      = var.google_api_key
    "jobseeker-google-drive-folder" = var.google_drive_folder_id
    "jobseeker-google-sheets-id"    = var.google_sheets_id
    "jobseeker-google-sheets-gid"   = var.google_sheets_gid
    "jobseeker-langsmith-api-key"   = var.langsmith_api_key
    "jobseeker-google-credentials"  = file(var.google_credentials_file)
    "jobseeker-google-token"        = file(var.google_token_file)
  }
}

resource "google_secret_manager_secret" "secrets" {
  for_each   = local.secrets
  secret_id  = each.key
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "versions" {
  for_each    = local.secrets
  secret      = google_secret_manager_secret.secrets[each.key].id
  secret_data = each.value
}

resource "google_secret_manager_secret_iam_member" "access" {
  for_each  = local.secrets
  secret_id = google_secret_manager_secret.secrets[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${data.google_compute_default_service_account.default.email}"
}

# ---------------------------------------------------------------------------
# Cloud Run
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "bot" {
  name                = "jobseeker-bot"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = data.google_compute_default_service_account.default.email
    timeout         = "3600s"

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.image

      resources {
        cpu_idle = true
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      # Plain env vars
      env {
        name  = "PYTHONUNBUFFERED"
        value = "1"
      }
      env {
        name  = "GOOGLE_CREDENTIALS_FILE"
        value = "/secrets/gcp-creds/credentials.json"
      }
      env {
        name  = "GOOGLE_TOKEN_FILE"
        value = "/secrets/gcp-token/token.json"
      }
      env {
        name  = "LANGSMITH_TRACING"
        value = "true"
      }
      env {
        name  = "LANGSMITH_ENDPOINT"
        value = var.langsmith_endpoint
      }
      env {
        name  = "LANGSMITH_PROJECT"
        value = var.langsmith_project
      }
      env {
        name  = "WEBHOOK_URL"
        value = var.webhook_url
      }
      env {
        name  = "COMPILER_SERVICE_URL"
        value = google_cloud_run_v2_service.compiler.uri
      }

      # Secret env vars
      dynamic "env" {
        for_each = {
          TELEGRAM_BOT_TOKEN     = "jobseeker-telegram-bot-token"
          TELEGRAM_USER_ID       = "jobseeker-telegram-user-id"
          GOOGLE_API_KEY         = "jobseeker-google-api-key"
          GOOGLE_DRIVE_FOLDER_ID = "jobseeker-google-drive-folder"
          GOOGLE_SHEETS_ID       = "jobseeker-google-sheets-id"
          GOOGLE_SHEETS_GID      = "jobseeker-google-sheets-gid"
          LANGSMITH_API_KEY      = "jobseeker-langsmith-api-key"
        }
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      # File-mounted secrets (each in its own directory)
      volume_mounts {
        name       = "gcp-creds"
        mount_path = "/secrets/gcp-creds"
      }
      volume_mounts {
        name       = "gcp-token"
        mount_path = "/secrets/gcp-token"
      }
    }

    volumes {
      name = "gcp-creds"
      secret {
        secret = google_secret_manager_secret.secrets["jobseeker-google-credentials"].secret_id
        items {
          path    = "credentials.json"
          version = "latest"
        }
      }
    }
    volumes {
      name = "gcp-token"
      secret {
        secret = google_secret_manager_secret.secrets["jobseeker-google-token"].secret_id
        items {
          path    = "token.json"
          version = "latest"
        }
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_version.versions,
    google_secret_manager_secret_iam_member.access,
  ]
}

# Allow Telegram to call the webhook (unauthenticated)
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.bot.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ---------------------------------------------------------------------------
# Compiler service (LaTeX → PDF + Drive upload)
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "compiler" {
  name                = "jobseeker-compiler"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = data.google_compute_default_service_account.default.email
    timeout         = "120s"

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = var.compiler_image

      resources {
        cpu_idle = false
        limits = {
          cpu    = "2"
          memory = "1Gi"
        }
      }

      env {
        name  = "PYTHONUNBUFFERED"
        value = "1"
      }
      env {
        name  = "GOOGLE_CREDENTIALS_FILE"
        value = "/secrets/gcp-creds/credentials.json"
      }
      env {
        name  = "GOOGLE_TOKEN_FILE"
        value = "/secrets/gcp-token/token.json"
      }

      # Drive folder ID from secret
      dynamic "env" {
        for_each = {
          GOOGLE_DRIVE_FOLDER_ID = "jobseeker-google-drive-folder"
        }
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = "gcp-creds"
        mount_path = "/secrets/gcp-creds"
      }
      volume_mounts {
        name       = "gcp-token"
        mount_path = "/secrets/gcp-token"
      }
    }

    volumes {
      name = "gcp-creds"
      secret {
        secret = google_secret_manager_secret.secrets["jobseeker-google-credentials"].secret_id
        items {
          path    = "credentials.json"
          version = "latest"
        }
      }
    }
    volumes {
      name = "gcp-token"
      secret {
        secret = google_secret_manager_secret.secrets["jobseeker-google-token"].secret_id
        items {
          path    = "token.json"
          version = "latest"
        }
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_version.versions,
    google_secret_manager_secret_iam_member.access,
  ]
}

# Bot can invoke the compiler (service-to-service)
resource "google_cloud_run_v2_service_iam_member" "bot_invokes_compiler" {
  name     = google_cloud_run_v2_service.compiler.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${data.google_compute_default_service_account.default.email}"
}

output "webhook_url" {
  value = google_cloud_run_v2_service.bot.uri
}

output "compiler_url" {
  value = google_cloud_run_v2_service.compiler.uri
}
