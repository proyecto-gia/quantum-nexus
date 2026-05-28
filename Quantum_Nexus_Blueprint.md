# 🧠 QUANTUM NEXUS v9 — UltraPlan / Blueprint

> **Protocolo:** `abuivangenesis` · **Fase:** Bootstrapping (100 USDT) · **Target:** Endgame Ready
> **Arquitectura:** Clean Architecture + Zero-Trust + Event-Driven Async
> **Autor del diseño:** The Architect (CTO / Lead Quant / DevSecOps)

---

## 1. Filosofía de Arquitectura

Quantum Nexus se diseña como un sistema distribuido **event-driven** y **asíncrono**, donde cada milisegundo cuenta. Se aplican tres principios no negociables:

1. **Clean Architecture** — Las reglas de negocio (estrategias, gestión de riesgo) no dependen de detalles externos (exchange, base de datos, transporte). Las dependencias apuntan siempre hacia el dominio.
2. **Zero-Trust** — Ninguna señal se ejecuta sin validación criptográfica del `Risk Auditor`. Nada se confía por defecto, ni siquiera los módulos internos.
3. **Fail-Safe by Default** — El estado por defecto es `PAPER`. El paso a `LIVE` exige Human-in-the-Loop + 2FA. El `Aegis` (Kill Switch) puede detener todo el enjambre en <50 ms.

---

## 2. Mapa de Componentes

| Capa | Módulo | Responsabilidad |
|------|--------|-----------------|
| **Núcleo / Orquestación** | `core/the_omnibus.py` | Bus de eventos asíncrono central. Pub/Sub en memoria. Punto único de coordinación. |
| | `core/cortex_ai.py` | Motor de decisión cuantitativa. Microestructura, señales, scoring. (diseño con *ultrathink*) |
| | `core/the_aegis.py` | **Kill Switch** + circuit breakers + límites de riesgo duros. (diseño con *ultrathink*) |
| **Ejecución** | `execution/executor_node.py` | Adaptador de exchange. HitL gate PAPER→LIVE. Event-driven. |
| | `execution/oracle.py` | Ingesta de datos de mercado vía WebSocket asíncrono. |
| **Telemetría** | `telemetry/observer.py` | Métricas, health checks, detección de memory leaks. |
| | `telemetry/command_center.py` | Estado global consolidado, panel de control. |
| | `telemetry/telegram_alerts.py` | Notificaciones críticas e inquebrantables vía Telegram. |
| **Agentes (LangGraph)** | `agents/orchestrator_node.py` | Gestiona el flujo de estado global y la delegación. |
| | `agents/executor_node.py` | Conecta APIs y maneja el framework event-driven. |
| | `agents/risk_auditor_node.py` | Intercepta y valida criptográficamente cada señal. |
| **Infra** | `infrastructure/Dockerfile` | Imagen no-root, multi-stage, basada en `uv`. |
| | `infrastructure/docker-compose.yml` | Orquestación de servicios + red aislada. |
| | `infrastructure/supabase_audit_logs.sql` | Tablas + RLS Insert-Only inmutable. |

---

## 3. Flujo de una Señal (Data → Order)

```
Oracle (WS tick)
   │  publica TickEvent
   ▼
The Omnibus (event bus)
   │  enruta a suscriptores
   ▼
Cortex AI  ──► genera Signal (con firma HMAC)
   │
   ▼
Risk Auditor Node  ──► valida firma + límites + Aegis status
   │   (rechaza → log + alerta Telegram)
   ▼  (aprueba)
Executor Node  ──► ¿ENV == LIVE? ──► HitL gate (input + 2FA)
   │
   ▼
Exchange API / Paper engine
   │
   ▼
Observer + Command Center  ──► telemetría → Supabase (INSERT-only) + Telegram
```

El **Aegis** observa transversalmente: si cualquier circuit breaker se dispara (drawdown, latencia, anomalía), emite `KillSwitchEvent` en el Omnibus y todo suscriptor debe detenerse.

---

## 4. Ecosistema Claude

- **Skills (`/claude_ecosystem`):** `hft_async_skill.md`, `zero_trust_skill.md`, `telegram_alert_skill.md`.
- **Rules:** `.clauderules` en raíz — estándares de código, prohibiciones de seguridad.
- **Hooks:** `.pre-commit-config.yaml` — secret scanner (detect-secrets), ruff, black, mypy.
- **MCP Connectors (conceptual):** `sqlite-mcp` para mocks locales de Supabase; `github-mcp` para versionado automático.

---

## 5. Optimización de Tokens y Pensamiento

| Tarea | Nivel | Justificación |
|-------|-------|---------------|
| Arquitectura matemática de Cortex AI | `> ultrathink` | Modelado de microestructura, scoring multifactor. |
| Lógica de contención de The Aegis | `> ultrathink` | Estados de fallo, circuit breakers concurrentes. |
| Orquestación Docker + APIs | `> think` | Configuración mecánica, riesgo medio. |
| Boilerplate / docstrings | normal | Sin razonamiento profundo. |

**Eficiencia:** `uv` para instalación silenciosa, logs estructurados (no verbosos), `/compact` tras cada módulo crítico, evitar PDFs (todo en markdown).

---

## 6. Seguridad (Zero-Trust)

1. **Sandboxing:** ejecución dentro de Docker **sin root** (usuario `nexus`).
2. **Supabase RLS:** tabla de telemetría **INSERT-only**; UPDATE/DELETE bloqueados matemáticamente (sin policy = denegado bajo RLS activo).
3. **HitL:** transición `PAPER → LIVE` requiere `input()` explícito + validación 2FA simulada.
4. **Firma de señales:** HMAC-SHA256 sobre cada señal; el Auditor rechaza firmas inválidas.
5. **Secret scanning:** pre-commit bloquea commits con credenciales.

---

## 7. Stress Test — Parámetros Exactos

- **Mock Server:** WebSocket local, productor de ticks.
- **Carga:** 10.000 ticks/s sostenidos durante 60 s (objetivo: 600.000 ticks).
- **Payload:** `{"symbol":"BTCUSDT","price":<float>,"volume":<float>,"timestamp":<ms_unix>}`.
- **Métricas:** latencia máx (ms), latencia media (ms), % paquetes perdidos, Δ RAM (memory-leak guard).

---

## 8. Secuencia de Entrega

1. ✅ `Quantum_Nexus_Blueprint.md` (este documento)
2. `.clauderules`, Skills `.md`, `.pre-commit-config.yaml`
3. `docker-compose.yml`, `Dockerfile`, `supabase_audit_logs.sql`
4. Skeleton code (interfaces, docstrings, asyncio setup)
5. `stress_test.py` listo para ejecutar

---

## 9. Notas de la Fase Bootstrapping (100 USDT)

> ⚠️ **Disclaimer operativo, no técnico:** 100 USDT es capital de *aprendizaje y calibración*. Antes de cualquier `ENV=LIVE`, completar validación de paper trading prolongada. El trading algorítmico apalancado puede perder el 100% del capital. Esta arquitectura es un andamiaje de software; no constituye asesoramiento financiero ni garantiza rendimiento.
