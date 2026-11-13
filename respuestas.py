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

FINALES = {"acepta", "declina"}      # cierran la solicitud; "error" no

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
            # Los encabezados se aseguran SIEMPRE, no solo al crear la pestaña: si la
            # pestaña ya existia vacia, o ya tiene respuestas sin encabezados, se
            # insertan en la fila 1 y lo que hubiera se recorre hacia abajo intacto.
            if [c.strip() for c in self._hoja.row_values(1)] != CAMPOS:
                self._hoja.insert_row(CAMPOS, 1)
        return self._hoja

    def guardar(self, registro: dict) -> dict:
        fila = {c: str(registro.get(c, "")) for c in CAMPOS}
        fila["fecha_hora"] = ahora()
        self.hoja().append_row([fila[c] for c in CAMPOS])
        return fila

    def leer(self) -> list:
        # Se lee por posicion de columna (el orden de CAMPOS), sin depender de lo
        # que diga la fila de encabezados.
        filas = self.hoja().get_all_values()[1:]
        return [dict(zip(CAMPOS, f + [""] * (len(CAMPOS) - len(f)))) for f in filas if any(f)]

    def estado_de(self, rfc: str, n: str):
        """La respuesta que rige para una solicitud (una persona puede tener dos).

        Aceptar y declinar son definitivas: la PRIMERA de ellas cierra la solicitud
        y cualquier fila posterior se ignora. Reportar un error no cierra nada: si
        solo hay reportes de error, rige el ultimo. Sin respuestas devuelve None.
        Para reabrir una solicitud cerrada, RH borra su fila en esta pestaña."""
        propias = [r for r in self.leer()
                   if str(r.get("rfc", "")).upper() == str(rfc).upper()
                   and str(r.get("n", "")) == str(n)]
        for r in propias:
            if r.get("decision") in FINALES:
                return r
        return propias[-1] if propias else None
