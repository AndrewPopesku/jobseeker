#!/usr/bin/env bash
set -euo pipefail

if [[ -f ".env" ]]; then
  set -o allexport
  source .env
  set +o allexport
fi

PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="${GCP_REGION:-europe-west1}"
BOT_IMAGE="gcr.io/${PROJECT_ID}/jobseeker-bot"
COMPILER_IMAGE="gcr.io/${PROJECT_ID}/jobseeker-compiler"

[[ -z "$PROJECT_ID" ]] && { echo "ERROR: GCP_PROJECT_ID not set" >&2; exit 1; }
[[ -f "Dockerfile" ]]  || { echo "ERROR: run from repo root" >&2; exit 1; }

gcloud config set project "$PROJECT_ID" --quiet
gcloud auth configure-docker --quiet

echo ">>> Building bot image..."
docker build --platform linux/amd64 -t "${BOT_IMAGE}:latest" .

echo ">>> Building compiler image..."
docker build --platform linux/amd64 -t "${COMPILER_IMAGE}:latest" -f compiler/Dockerfile .

echo ">>> Pushing images..."
docker push "${BOT_IMAGE}:latest"
docker push "${COMPILER_IMAGE}:latest"

BOT_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' "${BOT_IMAGE}:latest")
COMPILER_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' "${COMPILER_IMAGE}:latest")
echo ">>> Bot digest: $BOT_DIGEST"
echo ">>> Compiler digest: $COMPILER_DIGEST"

echo ">>> Applying Terraform..."
cd terraform
terraform init -upgrade -input=false

# Get existing service URL before apply (empty on first deploy)
WEBHOOK_URL=""
if gcloud run services describe jobseeker-bot --region "${REGION}" --quiet &>/dev/null 2>&1; then
  WEBHOOK_URL=$(gcloud run services describe jobseeker-bot --region "${REGION}" --format="value(status.url)" 2>/dev/null || true)
fi

TF_VARS=(
  -var="project_id=${PROJECT_ID}"
  -var="region=${REGION}"
  -var="image=${BOT_DIGEST}"
  -var="compiler_image=${COMPILER_DIGEST}"
  -var="telegram_bot_token=${TELEGRAM_BOT_TOKEN}"
  -var="telegram_user_id=${TELEGRAM_USER_ID}"
  -var="google_api_key=${GOOGLE_API_KEY}"
  -var="google_drive_folder_id=${GOOGLE_DRIVE_FOLDER_ID}"
  -var="google_sheets_id=${GOOGLE_SHEETS_ID}"
  -var="google_sheets_gid=${GOOGLE_SHEETS_GID}"
  -var="langsmith_api_key=${LANGSMITH_API_KEY}"
  -var="webhook_url=${WEBHOOK_URL}"
)

terraform apply -input=false -auto-approve "${TF_VARS[@]}"

# Get the actual URL from terraform output and re-apply if it changed
REAL_WEBHOOK_URL=$(terraform output -raw webhook_url)
if [[ "${REAL_WEBHOOK_URL}" != "${WEBHOOK_URL}" ]]; then
  echo ">>> Webhook URL changed to ${REAL_WEBHOOK_URL}, re-applying..."
  terraform apply -input=false -auto-approve "${TF_VARS[@]}" -var="webhook_url=${REAL_WEBHOOK_URL}"
fi

echo ">>> Webhook URL: ${REAL_WEBHOOK_URL}"
echo ">>> Compiler URL: $(terraform output -raw compiler_url)"
