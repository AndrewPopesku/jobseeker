FROM python:3.13-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

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

CMD ["uv", "run", "python", "telegram_bot.py"]
