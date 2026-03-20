FROM python:3.13-slim

# System deps for TinyTeX
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    perl \
    wget \
    xz-utils \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Install TinyTeX (minimal TeX Live)
ENV PATH="/root/bin:${PATH}"
RUN curl -sL "https://yihui.org/tinytex/install-bin-unix.sh" | sh

# Install ONLY the LaTeX packages the CV template uses
RUN tlmgr install \
      preprint    \
      titlesec    \
      marvosym    \
      enumitem    \
      fancyhdr    \
      fontawesome5 \
      fontaxes    \
      babel-english \
    && rm -rf /tmp/texlive* /tmp/install*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install Python dependencies
COPY compiler/pyproject.toml ./
RUN uv sync --no-dev

# Copy application code
COPY compiler/main.py ./

ENV PYTHONUNBUFFERED=1

# Verify pdflatex works at build time
COPY warmup.tex /tmp/warmup.tex
RUN cd /tmp && pdflatex -interaction=nonstopmode warmup.tex; \
    test -f /tmp/warmup.pdf && rm -f /tmp/warmup.*

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
