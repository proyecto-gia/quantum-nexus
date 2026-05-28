---
name: telegram_alert
description: Notificaciones críticas e inquebrantables de estado vía Telegram Bot API.
---

# Skill: Telegram Critical Alerts

## Cuándo activar
Eventos críticos: kill switch disparado, transición LIVE, drawdown límite, error fatal, fin de stress test.

## Garantías
- **Inquebrantable**: el fallo del canal de alertas NUNCA debe tumbar el sistema. Try/except + retry con backoff exponencial; si Telegram cae, se loguea localmente y se reintenta.
- **Async**: envío vía `aiohttp`, no bloquea el event loop.
- **Niveles**: INFO / WARN / CRITICAL. CRITICAL siempre se entrega (cola persistente de reintentos).

## Patrón
```python
async def send(text: str, level: str = "INFO") -> None:
    # POST https://api.telegram.org/bot<TOKEN>/sendMessage
    # retry con backoff; jamás propagar excepción al caller crítico
    ...
```

## Seguridad
- TOKEN y CHAT_ID sólo desde entorno. Nunca en logs ni en el mensaje.
