#!/usr/bin/env python3
"""Capa de datos. La fuente es el Google Sheet, no archivos locales.

Aqui no se guarda ningun dato de personal: todo se lee en vivo del Sheet.

Configuracion (cualquiera de las dos):
  - Dentro de Streamlit: st.secrets["sheet_id"] y st.secrets["gcp_service_account"]
  - Fuera de Streamlit:  variables de entorno SHEET_ID y GOOGLE_SERVICE_ACCOUNT_JSON
                         (ruta al json de la cuenta de servicio)
"""

import difflib
import os
import unicodedata
from dataclasses import dataclass, field

ALCANCE = ["https://www.googleapis.com/auth/spreadsheets"]

HOJA_EMPLEADOS = "De interes"
HOJA_DIRECTORIO = "directorio"
FILA_ENCABEZADO = 2          # en tu Sheet el titulo ocupa la fila 1

# La plantilla solo tiene 4 renglones para claves presupuestales.
MAX_CLAVES = 4


# ---------------------------------------------------------------- conexion

def abrir_libro(secrets=None, sheet_id=None):
    """Devuelve el Google Sheet abierto. secrets viene de Streamlit si lo hay."""
    import gspread
    from google.oauth2.service_account import Credentials

    if secrets and "gcp_service_account" in secrets:
        cred = Credentials.from_service_account_info(
            dict(secrets["gcp_service_account"]), scopes=ALCANCE)
        sheet_id = sheet_id or secrets["sheet_id"]
    else:
        ruta = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "credenciales.json")
        if not os.path.exists(ruta):
            raise RuntimeError(
                f"No encuentro las credenciales en {ruta!r}. Pon la ruta del json de la "
                "cuenta de servicio en GOOGLE_SERVICE_ACCOUNT_JSON.")
        cred = Credentials.from_service_account_file(ruta, scopes=ALCANCE)
        sheet_id = sheet_id or os.environ.get("SHEET_ID")

    if not sheet_id:
        raise RuntimeError("Falta el id del Sheet (secrets['sheet_id'] o SHEET_ID).")
    return gspread.authorize(cred).open_by_key(sheet_id)


# ---------------------------------------------------------------- normalizacion

def sin_acentos(s) -> str:
    s = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")

def limpio(s) -> str:
    return " ".join(str(s or "").split()).strip()

# El Sheet trae la DEPENDENCIA ("SUBSECRETARÍA DE EDUCACIÓN MEDIA SUPERIOR") y el
# directorio trae el CARGO ("Subsecretario de Educación Media Superior"). Para
# cruzarlos se le quita a ambos el prefijo de cargo y queda la materia en comun:
# "EDUCACION MEDIA SUPERIOR". Se prueban de mas largo a mas corto.
PREFIJOS = sorted([
    "ENCARGADA DEL DESPACHO DE LA DIRECCION GENERAL DE",
    "ENCARGADO DEL DESPACHO DE LA DIRECCION GENERAL DE",
    "ENCARGADA DEL DESPACHO DE LA DIRECCION DE",
    "ENCARGADO DEL DESPACHO DE LA DIRECCION DE",
    "ENCARGADA DEL DESPACHO DE LA DELEGACION",
    "ENCARGADO DEL DESPACHO DE LA DELEGACION",
    "ENCARGADA DEL DESPACHO DEL AREA DE",
    "ENCARGADO DEL DESPACHO DEL AREA DE",
    "ENCARGADA DEL DESPACHO DE LA", "ENCARGADO DEL DESPACHO DE LA",
    "ENCARGADA DEL DESPACHO DE", "ENCARGADO DEL DESPACHO DE",
    "SUBSECRETARIA DE", "SUBSECRETARIO DE",
    "DIRECCION GENERAL DE", "DIRECTORA GENERAL DE", "DIRECTOR GENERAL DE",
    "DIRECCION DE", "DIRECTORA DE", "DIRECTOR DE",
    "DELEGACION REGIONAL DE", "DELEGACION DE", "DELEGACION",
    "SUBDELEGACION REGIONAL DE LA", "SUBDELEGACION REGIONAL DE", "SUBDELEGACION DE",
    "AREA DE", "COORDINACION DE", "JEFATURA DE", "SUPERVISION DE",
], key=len, reverse=True)

def nucleo(nombre) -> str:
    s = " ".join(sin_acentos(nombre).upper().split())
    for p in PREFIJOS:
        if s.startswith(p + " "):
            return s[len(p) + 1:].strip()
    return s


# ---------------------------------------------------------------- directorio

@dataclass
class Director:
    titular: str = ""
    cargo: str = ""
    estado: str = "falta"        # ok | aproximado | falta

def directorio_desde_filas(filas) -> dict:
    """filas: lista de dicts con las columnas dependencia_cargo y titular."""
    idx = {}
    for f in filas:
        cargo = limpio(f.get("dependencia_cargo"))
        titular = limpio(f.get("titular"))
        if cargo and titular:
            idx[nucleo(cargo)] = (titular, cargo)
    return idx

def resolver_director(centro_nombre, idx) -> Director:
    k = nucleo(centro_nombre)
    if not k:
        return Director()
    if k in idx:
        return Director(*idx[k], "ok")
    cerca = difflib.get_close_matches(k, list(idx), n=1, cutoff=0.86)
    if cerca:
        return Director(*idx[cerca[0]], "aproximado")
    return Director()


# ---------------------------------------------------------------- empleados

@dataclass
class Empleado:
    n: str
    nombre: str
    rfc: str
    sostenimiento: str
    claves: list
    correo: str
    telefono: str
    ct_actual_clave: str
    ct_actual_nombre: str
    ct_solicitado_clave: str
    ct_solicitado_nombre: str
    estatus: str = ""            # PEDIR (entra a la DFC) | PRESTADO (sale de la DFC)
    libera: Director = field(default_factory=Director)
    recibe: Director = field(default_factory=Director)

    @property
    def es_estatal(self) -> bool:
        return sin_acentos(self.sostenimiento).upper().startswith("EST")

    def problemas(self) -> list:
        """Lo que impide generar o firmar el formato. Lista vacia = listo."""
        p = []
        if len(self.rfc) != 13:
            p.append(f"RFC invalido ({self.rfc or 'vacio'})")
        if not self.correo:
            p.append("sin correo")
        if not self.telefono:
            p.append("sin teléfono")
        if not (self.ct_solicitado_clave and self.ct_solicitado_nombre):
            p.append("sin centro de trabajo solicitado")
        if not self.claves:
            p.append("sin clave presupuestal")
        if len(self.claves) > MAX_CLAVES:
            p.append(f"{len(self.claves)} claves y el formato solo tiene {MAX_CLAVES}")
        if self.libera.estado != "ok":
            p.append(f"sin titular que libere ({self.ct_actual_nombre or 'sin centro'})")
        if self.recibe.estado != "ok":
            p.append(f"sin titular que reciba ({self.ct_solicitado_nombre or 'sin centro'})")
        return p


def _claves(valor) -> list:
    # En el Sheet van separadas por coma; los espacios internos son parte de la clave.
    return [limpio(c) for c in str(valor or "").replace(";", ",").split(",") if limpio(c)]

# Se busca por el encabezado, no por posicion, para que mover una columna en el
# Sheet no rompa la app. Cada campo acepta varias formas de escribirlo.
COLUMNAS = {
    "n": ["N°", "N", "NO", "NUM"],
    "nombre": ["NOMBRE"],
    "rfc": ["RFC"],
    "sostenimiento": ["SOSTENIMIENTO"],
    "claves": ["CLAVE(S) PRESUPUESTALES", "CLAVES PRESUPUESTALES", "CLAVE PRESUPUESTAL"],
    "correo": ["CORREO ELECTRONICO", "CORREO"],
    "telefono": ["TELEFONO", "TEL"],
    "ct_actual_clave": ["CENTRO DE TRABAJO ACTUAL"],
    "ct_actual_nombre": ["NOMBRE DEL CENTRO DE TRABAJO ACTUAL"],
    "ct_solicitado_clave": ["CENTRO DE TRABAJO SOLICITADO"],
    "ct_solicitado_nombre": ["NOMBRE DEL CENTRO DE TRABAJO SOLICITADO"],
    "estatus": ["ESTATUS", "PEDIR/PRESTADO", "TIPO"],
}

def _mapa_columnas(encabezados) -> dict:
    normal = [sin_acentos(h).upper().strip() for h in encabezados]
    mapa = {}
    for campo, opciones in COLUMNAS.items():
        for o in opciones:
            if sin_acentos(o).upper() in normal:
                mapa[campo] = normal.index(sin_acentos(o).upper())
                break
    faltan = [c for c in COLUMNAS if c not in mapa and c != "estatus"]
    if faltan:
        raise RuntimeError(
            "Al Sheet le faltan columnas: " + ", ".join(faltan) +
            ". Encabezados encontrados: " + ", ".join(h for h in encabezados if h))
    return mapa

def empleados_desde_filas(filas) -> list:
    """filas: matriz de celdas, la primera es el renglon de encabezados."""
    if not filas:
        return []
    mapa = _mapa_columnas(filas[0])

    def val(fila, campo):
        i = mapa.get(campo)
        return limpio(fila[i]) if i is not None and i < len(fila) else ""

    out = []
    for fila in filas[1:]:
        if not val(fila, "nombre"):
            continue
        out.append(Empleado(
            n=val(fila, "n"), nombre=val(fila, "nombre"),
            rfc=val(fila, "rfc").upper(), sostenimiento=val(fila, "sostenimiento"),
            claves=_claves(fila[mapa["claves"]] if mapa["claves"] < len(fila) else ""),
            correo=val(fila, "correo").lower(), telefono=val(fila, "telefono"),
            ct_actual_clave=val(fila, "ct_actual_clave"),
            ct_actual_nombre=val(fila, "ct_actual_nombre"),
            ct_solicitado_clave=val(fila, "ct_solicitado_clave"),
            ct_solicitado_nombre=val(fila, "ct_solicitado_nombre"),
            estatus=val(fila, "estatus"),
        ))
    return out


def con_directores(empleados, idx) -> list:
    """Quien libera es el titular del centro ACTUAL y quien recibe el del SOLICITADO.
    Sirve igual para los que entran a la DFC (PEDIR) y los que salen (PRESTADO)."""
    for e in empleados:
        e.libera = resolver_director(e.ct_actual_nombre, idx)
        e.recibe = resolver_director(e.ct_solicitado_nombre, idx)
    return empleados


def cargar(libro) -> list:
    """Lee el Sheet ya abierto y devuelve los empleados con sus directores resueltos."""
    filas = libro.worksheet(HOJA_EMPLEADOS).get_all_values()[FILA_ENCABEZADO - 1:]
    idx = directorio_desde_filas(libro.worksheet(HOJA_DIRECTORIO).get_all_records())
    return con_directores(empleados_desde_filas(filas), idx)
