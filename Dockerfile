FROM python:3.13-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install tectonic (LaTeX → PDF compiler)
RUN curl -fsSL \
    "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.15.0/tectonic-0.15.0-x86_64-unknown-linux-musl.tar.gz" \
    | tar -xz -C /usr/local/bin/ \
    && chmod +x /usr/local/bin/tectonic

# Install uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install Python dependencies (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY telegram_bot.py ./
COPY jobseeker/ ./jobseeker/

# Pre-create artifact storage dir
RUN mkdir -p /app/jobseeker/.adk/artifacts

ENV PYTHONUNBUFFERED=1
# Tectonic package cache — survives as long as the container lives
ENV TECTONIC_CACHE_DIR=/tmp/tectonic-cache

# Google OAuth token + credentials are mounted at runtime as secrets:
#   /app/jobseeker/credentials.json  (from Secret Manager or volume)
#   /app/jobseeker/token.json        (pre-authorised offline token)

CMD ["uv", "run", "python", "telegram_bot.py"]
