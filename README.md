# Quantum Nexus v9

Institutional-grade algorithmic trading ecosystem built on **Clean Architecture**, **Zero-Trust**, and **event-driven async** principles.

> Phase: Bootstrapping (100 USDT) — default state is `PAPER`. Transition to `LIVE` requires Human-in-the-Loop + 2FA.

---

## Architecture

```
Oracle (WebSocket tick)
   │  publishes TickEvent
   ▼
The Omnibus (async event bus)
   │  routes to subscribers
   ▼
Cortex AI  ──► generates Signal (HMAC-signed)
   │
   ▼
Risk Auditor  ──► validates signature + Aegis status
   │   (reject → log + Telegram alert)
   ▼  (approve)
Executor  ──► ENV == LIVE? ──► HitL gate (input + 2FA)
   │
   ▼
Exchange API / Paper engine
   │
   ▼
Observer + Command Center  ──► telemetry → Supabase + Telegram
```

**The Aegis** monitors transversally: any circuit breaker (drawdown, latency, pipeline saturation) fires a `KillSwitchEvent` that halts the entire swarm in <50 ms.

---

## Modules

| Layer | Module | Role |
|-------|--------|------|
| Core | `core/the_omnibus.py` | Async in-memory pub/sub event bus with backpressure |
| Core | `core/cortex_ai.py` | Quantitative decision engine — pluggable `Strategy` interface |
| Core | `core/the_aegis.py` | Kill switch + circuit breakers (drawdown / latency / drops) |
| Core | `core/domain.py` | Shared domain models (Pydantic v2) |
| Execution | `execution/oracle.py` | Market data ingestion via async WebSocket |
| Execution | `execution/executor_node.py` | Exchange adapter with HitL PAPER→LIVE gate |
| Agents | `agents/orchestrator_node.py` | LangGraph-style flow: decide → audit → execute |
| Agents | `agents/risk_auditor_node.py` | HMAC-SHA256 signature verification + Aegis check |
| Agents | `agents/executor_node.py` | Event-driven agent bridge (SIGNAL → Executor) |
| Telemetry | `telemetry/observer.py` | Metrics and memory-leak guard (psutil) |
| Telemetry | `telemetry/command_center.py` | Consolidated global state panel |
| Telemetry | `telemetry/telegram_alerts.py` | Non-blocking critical alerts (never crashes the system) |
| Infra | `infrastructure/Dockerfile` | Non-root multi-stage image (uv-based) |
| Infra | `infrastructure/docker-compose.yml` | Isolated network, read-only FS, no capabilities |
| Infra | `infrastructure/supabase_audit_logs.sql` | INSERT-only RLS telemetry table |

---

## Security (Zero-Trust)

- **Signal signing**: every `Signal` is HMAC-SHA256 signed by Cortex AI and verified by the Risk Auditor before reaching the Executor. Invalid signature → instant reject.
- **Default-deny DB**: Supabase RLS active — only INSERT policy exists. UPDATE/DELETE are mathematically impossible while FORCE ROW LEVEL SECURITY is on.
- **No-root containers**: Docker image runs as user `nexus` (UID 10001), all Linux capabilities dropped.
- **HitL gate**: no automated path to `LIVE`. Requires explicit `input()` confirmation + 2FA code.
- **Secret scanning**: pre-commit hook via `detect-secrets` blocks any commit containing credentials.

---

## Stress Test Results

10,000 ticks/s sustained for 60 seconds:

| Metric | Result |
|--------|--------|
| Ticks sent | 599,919 |
| Throughput | 9,998 ticks/s |
| Avg latency | 1.25 ms |
| Max latency | 35.2 ms |
| Packet loss | 0.000 % |
| RAM delta | +0.11 MB |

---

## Getting Started

```bash
# Install dependencies
pip install -e ".[dev]"

# Run tests (16 unit tests)
pytest

# Stress test — quick smoke run (2s)
python stress_test.py --quick

# Stress test — full run (60s)
python stress_test.py

# Docker
cd infrastructure && docker compose up --build
```

### Environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `ENV` | `PAPER` (default) or `LIVE` |
| `HMAC_SECRET` | 32+ byte random secret for signal signing |
| `TWO_FA_CODE` | Simulated 2FA code for LIVE transition |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon/service key |
| `TELEGRAM_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Telegram chat ID for alerts |

---

## Disclaimer

> 100 USDT is learning and calibration capital. Before any `ENV=LIVE`, complete extended paper trading validation. Algorithmic leveraged trading can lose 100% of capital. This architecture is a software scaffold — it does not constitute financial advice or guarantee performance.
