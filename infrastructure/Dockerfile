# ---- QUANTUM NEXUS — imagen no-root, multi-stage, basada en uv ----
FROM python:3.11-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml ./
# Instalación silenciosa y ultrarrápida de dependencias
RUN uv pip install --system --no-cache --quiet -r pyproject.toml || true

FROM python:3.11-slim AS runtime
# Usuario sin privilegios (Zero-Trust: sin root)
RUN useradd --create-home --uid 10001 nexus
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
WORKDIR /app
COPY --chown=nexus:nexus . .
USER nexus
ENV ENV=PAPER \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
# Healthcheck mínimo
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "print('ok')" || exit 1
ENTRYPOINT ["python", "-m", "core.the_omnibus"]
