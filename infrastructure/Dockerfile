# ---- QUANTUM NEXUS — imagen no-root, multi-stage ----
#
# Stage 1 (builder): instala dependencias.
#   Layer cacheada mientras pyproject.toml no cambie.
# Stage 2 (runtime): imagen mínima, usuario sin privilegios.

FROM python:3.13-slim AS builder
WORKDIR /app

# Copiar solo el manifiesto de dependencias para aprovechar la cache de capas.
# Se crean stubs mínimos para que pip pueda resolver el paquete sin el código fuente.
COPY pyproject.toml ./
RUN mkdir -p core agents execution telemetry backtesting && \
    for d in core agents execution telemetry backtesting; do touch "$d/__init__.py"; done && \
    touch main.py && \
    pip install --no-cache-dir . && \
    rm -rf /root/.cache

# ---- runtime ----
FROM python:3.13-slim AS runtime

# Usuario sin privilegios (Zero-Trust: sin root en contenedor)
RUN useradd --create-home --uid 10001 nexus

# Copiar paquetes instalados desde el builder
COPY --from=builder /usr/local/lib/python3.13/site-packages \
                    /usr/local/lib/python3.13/site-packages

WORKDIR /app
COPY --chown=nexus:nexus . .
USER nexus

ENV ENV=PAPER \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Healthcheck: el proceso escribe /tmp/nexus_heartbeat cada 30 s.
# Falla si el último heartbeat tiene más de 120 s de antigüedad.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c \
        "import time, sys; ts=float(open('/tmp/nexus_heartbeat').read()); sys.exit(0 if time.time()-ts<120 else 1)" \
        2>/dev/null || exit 1

ENTRYPOINT ["python", "main.py"]
