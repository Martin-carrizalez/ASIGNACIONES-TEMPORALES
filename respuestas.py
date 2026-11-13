#!/usr/bin/env python3
"""Guarda en el mismo Google Sheet lo que contesta cada trabajador.

Escribe en la hoja 'respuestas', que se crea sola la primera vez.
No se guarda nada en disco.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import datos

HOJA = "respuestas"
ZONA = ZoneInfo("America/Mexico_City")

CAMPOS = [
    "fecha_hora", "n", "rfc", "nombre_en_relacion", "decision",
    "nombre_corregido", "correo_corregido", "telefono_corregido", "observaciones",
]

DECISIONES = {
    "acepta": "Datos correctos, acepta la asignación",
    "error": "Reporta un error en sus datos",
    "declina": "No desea continuar",
}


def ahora() -> str:
    return datetime.now(ZONA).strftime("%Y-%m-%d %H:%M:%S")


class Almacen:
    def __init__(self, secrets=None, sheet_id=None, libro=None):
        self._libro = libro
        self._secrets, self._sheet_id = secrets, sheet_id
        self._hoja = None

    def hoja(self):
        if self._hoja is None:
            libro = self._libro or datos.abrir_libro(self._secrets, self._sheet_id)
            try:
                self._hoja = libro.worksheet(HOJA)
            except Exception:
                self._hoja = libro.add_worksheet(HOJA, rows=500, cols=len(CAMPOS))
                self._hoja.append_row(CAMPOS)
        return self._hoja

    def guardar(self, registro: dict) -> dict:
        fila = {c: str(registro.get(c, "")) for c in CAMPOS}
        fila["fecha_hora"] = ahora()
        self.hoja().append_row([fila[c] for c in CAMPOS])
        return fila

    def leer(self) -> list:
        return self.hoja().get_all_records()

    def ultima_de(self, rfc: str, n: str):
        """Ultima respuesta de una solicitud concreta: una persona puede tener dos."""
        previas = [r for r in self.leer()
                   if str(r.get("rfc", "")).upper() == str(rfc).upper()
                   and str(r.get("n", "")) == str(n)]
        return previas[-1] if previas else None
