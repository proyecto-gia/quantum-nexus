---
name: hft_async
description: Patrones de concurrencia asíncrona para sistemas HFT de baja latencia en Python.
---

# Skill: HFT Async Engineering

## Cuándo activar
Al diseñar o revisar código de ingesta de mercado, event bus, o cualquier ruta crítica de latencia.

## Principios
1. **Un solo event loop** por proceso. Nunca crear loops anidados.
2. **Backpressure**: usa `asyncio.Queue(maxsize=N)` acotadas. Si la cola se llena, descarta el tick más viejo y cuenta el drop (no bloquees el productor).
3. **Cero bloqueo**: prohibido `time.sleep`, requests síncronos, o CPU-bound largo en el loop. CPU-bound → `loop.run_in_executor`.
4. **Hot path sin allocations**: reusa objetos/buffers en la ruta tick→signal. Evita logging en hot path; bufferiza y flushea async.
5. **uvloop** opcional para acelerar el loop en Linux.

## Medición
- Timestamp monotónico (`time.perf_counter_ns`) en entrada y salida de cada etapa.
- Reporta p50, p99, máx. Nunca solo el promedio.
- Vigila Δ RSS (RAM) para detectar leaks: medir antes/después de la carga.

## Anti-patrones
- `await` dentro de un bucle apretado sin `gather`/`as_completed`.
- Crear una task por tick sin límite (explosión de memoria).
- Logear cada tick a stdout (mata la latencia).
