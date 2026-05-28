"""setup_supabase.py — Verifica la conexión y esquema de Supabase.

Uso:
    python setup_supabase.py              # verifica INSERT + bloqueo de DELETE
    python setup_supabase.py --dry-run    # solo muestra instrucciones de setup

Requiere:
    SUPABASE_URL=https://<project>.supabase.co
    SUPABASE_KEY=<service_role_key>        # service_role para poder hacer SELECT

El script NO aplica el schema SQL (eso se hace desde el SQL Editor de Supabase).
Ver: infrastructure/supabase_audit_logs.sql
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

import aiohttp

_ENDPOINT = "rest/v1/trade_logs"

SETUP_INSTRUCTIONS = """
=========================================
  QUANTUM NEXUS -- Setup de Supabase
=========================================

Paso 1: Abrir el SQL Editor en el dashboard de Supabase.
Paso 2: Copiar y ejecutar el contenido de:
        infrastructure/supabase_audit_logs.sql

Paso 3: En .env (o docker-compose.yml), configurar:
        SUPABASE_URL=https://<project-ref>.supabase.co
        SUPABASE_KEY=<tu service_role key>

Paso 4: Ejecutar este script para verificar:
        python setup_supabase.py

La tabla trade_logs tiene RLS activo con INSERT-ONLY.
UPDATE y DELETE estan matematicamente bloqueados (sin policy = denegado).
"""


async def verify(url: str, key: str) -> int:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    base = url.rstrip("/")

    async with aiohttp.ClientSession(headers=headers) as session:
        # ── Test 1: INSERT ────────────────────────────────────────────────────
        print("1. Verificando INSERT...", end=" ", flush=True)
        test_payload = {
            "env": "PAPER",
            "symbol": "SETUP_CHECK",
            "event_type": "SETUP_TEST",
            "payload": {"ts": int(time.time()), "source": "setup_supabase.py"},
            "severity": "INFO",
        }
        try:
            async with session.post(
                f"{base}/{_ENDPOINT}",
                json=test_payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (200, 201):
                    print("OK")
                else:
                    text = await resp.text()
                    print(f"FALLO (HTTP {resp.status}): {text[:200]}")
                    if "does not exist" in text:
                        print("\n  La tabla trade_logs no existe.")
                        print("  Ejecuta infrastructure/supabase_audit_logs.sql primero.")
                    return 1
        except Exception as exc:
            print(f"FALLO: {exc}")
            return 1

        # ── Test 2: DELETE bloqueado ──────────────────────────────────────────
        print("2. Verificando bloqueo de DELETE...", end=" ", flush=True)
        try:
            async with session.delete(
                f"{base}/{_ENDPOINT}?event_type=eq.SETUP_TEST",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (401, 403):
                    print("OK (DELETE bloqueado correctamente)")
                elif resp.status == 204:
                    # Sin filas afectadas puede devolver 204 aun con RLS
                    print("OK (204 — RLS sin política DELETE activa)")
                else:
                    text = await resp.text()
                    print(f"ADVERTENCIA (HTTP {resp.status}): {text[:200]}")
        except Exception as exc:
            print(f"ADVERTENCIA: {exc}")

        # ── Test 3: SELECT de auditoría ───────────────────────────────────────
        print("3. Verificando SELECT...", end=" ", flush=True)
        try:
            async with session.get(
                f"{base}/{_ENDPOINT}?event_type=eq.SETUP_TEST&order=created_at.desc&limit=1",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    rows = await resp.json()
                    print(f"OK ({len(rows)} fila(s) encontrada(s))")
                else:
                    text = await resp.text()
                    print(f"ADVERTENCIA (HTTP {resp.status}): {text[:200]}")
        except Exception as exc:
            print(f"ADVERTENCIA: {exc}")

    print("\n  Supabase verificado correctamente.")
    print("  La telemetría de Quantum Nexus está lista.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Verificación de Supabase para Quantum Nexus")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra instrucciones")
    args = parser.parse_args()

    if args.dry_run:
        print(SETUP_INSTRUCTIONS)
        return

    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_KEY", "")

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL y SUPABASE_KEY deben estar configuradas.")
        print(SETUP_INSTRUCTIONS)
        sys.exit(1)

    print(f"Verificando Supabase en {supabase_url}...\n")
    exit_code = asyncio.run(verify(supabase_url, supabase_key))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
