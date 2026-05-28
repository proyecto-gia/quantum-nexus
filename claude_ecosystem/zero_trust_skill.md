---
name: zero_trust
description: Modelo de seguridad Zero-Trust para firmar/validar señales y aislar la ejecución.
---

# Skill: Zero-Trust Security

## Cuándo activar
Al generar o ejecutar señales de trading, manejar credenciales, o configurar contenedores/DB.

## Reglas
1. **Firma de señales (HMAC-SHA256)**: cada Signal se firma con un secret de entorno. El Risk Auditor recomputa y compara con `hmac.compare_digest`. Firma inválida → rechazo + alerta.
2. **Default-deny en DB**: con RLS activo, ausencia de policy = denegado. La tabla de auditoría sólo tiene policy de INSERT.
3. **Sin root**: contenedores corren como usuario no privilegiado. Sin capacidades extra, sin volúmenes sensibles montados RW.
4. **Secretos por entorno**: jamás en código ni en logs. Pre-commit escanea secretos.
5. **HitL para LIVE**: ningún path automático activa órdenes reales.
6. **Least privilege**: el Executor sólo recibe señales ya validadas; no lee la lógica de Cortex.

## Validación criptográfica (patrón)
```python
import hmac, hashlib
def sign(payload: bytes, secret: bytes) -> str:
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()
def verify(payload: bytes, secret: bytes, sig: str) -> bool:
    return hmac.compare_digest(sign(payload, secret), sig)
```
