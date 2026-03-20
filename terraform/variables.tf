variable "project_id" {}
variable "region" { default = "europe-west1" }
variable "image" {}
variable "compiler_image" {}

variable "telegram_bot_token"   { sensitive = true }
variable "telegram_user_id"     { sensitive = true }
variable "google_api_key"       { sensitive = true }
variable "google_drive_folder_id" {}
variable "google_sheets_id"     {}
variable "google_sheets_gid"    {}
variable "langsmith_api_key"    { sensitive = true }
variable "langsmith_endpoint"   { default = "https://eu.api.smith.langchain.com" }
variable "langsmith_project"    { default = "jobseeker" }

variable "google_credentials_file" { default = "../jobseeker/credentials.json" }
variable "google_token_file"       { default = "../jobseeker/token.json" }

variable "webhook_url" { default = "https://placeholder.run.app" }
