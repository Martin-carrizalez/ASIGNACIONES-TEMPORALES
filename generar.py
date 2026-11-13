#!/usr/bin/env python3
"""Genera un FORMATO DE ASIGNACION TEMPORAL por empleado.

Llena la plantilla original sin reconstruirla: la abre y escribe sobre sus celdas,
asi conserva los logos del pie, los margenes, las fuentes y la nota legal.

Lee los datos del Google Sheet (variables SHEET_ID y GOOGLE_SERVICE_ACCOUNT_JSON).

    python3 generar.py                 # genera solo los expedientes sin problemas
    python3 generar.py --todos         # genera tambien los incompletos, con huecos
"""

import io
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph

import datos

BASE = Path(__file__).parent
PLANTILLA = BASE / "templates" / "FORMATO_ASIGNACION_TEMPORAL_2026.docx"
SALIDA = BASE / "salida"

# Fecha del tramite. Vacia = se pone a mano al firmar.
# Importa por la nota del formato: dentro de los primeros cinco dias habiles del
# mes surte efectos el dia 16; despues, el primero del mes siguiente.
FECHA = ""

FUENTE = "Arial"
TAM_DATO = Pt(9)
TAM_PIE = Pt(8)

# ---------------------------------------------------------------- utilidades docx

def _nuevo_run(parrafo, texto, tam=TAM_DATO, bold=False):
    r = parrafo.add_run(texto)
    r.font.name, r.font.size, r.bold = FUENTE, tam, bold
    return r

def escribir(celda, texto, bold=False):
    """Escribe en una celda vacia de la plantilla."""
    p = celda.paragraphs[0]
    for r in list(p.runs):
        r._element.getparent().remove(r._element)
    _nuevo_run(p, texto, bold=bold)

def anexar(celda, texto):
    """Agrega el valor despues de una etiqueta existente: 'Nombre:' -> 'Nombre: X'."""
    _nuevo_run(celda.paragraphs[0], " " + texto)

def parrafo_antes(parrafo, texto, tam=TAM_PIE, bold=True):
    """Inserta una linea centrada arriba del pie de firma, sin tocar el pie."""
    nuevo = OxmlElement("w:p")
    parrafo._p.addprevious(nuevo)
    np = Paragraph(nuevo, parrafo._parent)
    np.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _nuevo_run(np, texto, tam=tam, bold=bold)

MARCA = " (X)"

def _marcar_opcion(elementos_t, opcion: str) -> int:
    """Escribe ' (X)' junto a la palabra de la opcion elegida.

    Las casillas redondeadas del formato son figuras con cuadro de texto. Escribir
    la X dentro de la figura NO sirve: las que estan ancladas en una celda de tabla
    no imprimen su texto en LibreOffice ni en varios visores, y el formato sale sin
    marcar sin que nadie se de cuenta. Por eso la marca va en el texto mismo, que
    imprime igual en cualquier visor. Se consumen espacios a la derecha para no
    recorrer el resto del renglon."""
    marcados = 0
    for t in elementos_t:
        texto = t.text or ""
        if opcion not in texto or MARCA in texto:
            continue
        i = texto.index(opcion) + len(opcion)
        cola = texto[i:]
        sobrantes = len(cola) - len(cola.lstrip(" "))
        recorte = min(sobrantes, len(MARCA))
        t.text = texto[:i] + MARCA + cola[recorte:]
        t.set(qn("xml:space"), "preserve")
        marcados += 1
    return marcados

def _textos(nodo):
    return [t for t in nodo.iter(qn("w:t"))]

def marcar_casillas(doc, celda_sostenimiento, es_estatal):
    """Marca Sostenimiento (Estatal/Federal) y Descripcion del movimiento (Temporal).
    La fila de 'Descripcion del movimiento' es una figura y Word la guarda dos veces,
    version moderna (mc:Choice) y respaldo VML (mc:Fallback): hay que marcar las dos
    o segun el visor se ve sin marcar."""
    opcion = "Estatal" if es_estatal else "Federal"
    if not _marcar_opcion(_textos(celda_sostenimiento._tc), opcion):
        raise RuntimeError(f"No se encontro la opcion {opcion!r} en la fila de sostenimiento.")

    cajas = [tb for tb in doc.element.body.iter()
             if tb.tag.endswith("txbxContent") and "Temporal" in "".join(tb.itertext())]
    if not cajas:
        raise RuntimeError("No se encontro la fila 'Descripcion del movimiento' en la plantilla.")
    for caja in cajas:           # todas son asignacion temporal, nunca definitivo
        _marcar_opcion(_textos(caja), "Temporal")

def recuperar_renglones(doc, cuantos):
    """Imprimir los nombres abajo de cada firma empuja el documento y el bloque de
    firmas se encima con el pie de pagina. Se quitan renglones en blanco del hueco
    muerto que hay entre el bloque del solicitante y 'Libera el recurso', para no
    comerse el espacio donde la gente realmente firma."""
    cuerpo = list(doc.element.body.iterchildren())
    tablas = [i for i, c in enumerate(cuerpo) if c.tag == qn("w:tbl")]
    quitados = 0
    for c in cuerpo[tablas[2] + 1:]:
        if quitados >= cuantos or c.tag != qn("w:p"):
            break
        if not "".join(c.itertext()).strip():
            c.getparent().remove(c)
            quitados += 1
    return quitados

# ---------------------------------------------------------------- generacion

def generar(emp, destino):
    doc = Document(str(PLANTILLA))

    if FECHA:
        for p in doc.paragraphs:
            if "Fecha:" in p.text:
                for r in p.runs:
                    if "_" in r.text:
                        r.text = f"  {FECHA}"
                        break
                break

    t_datos, t_centros, t_solicitante, t_firmas = doc.tables[:4]

    escribir(t_datos.rows[0].cells[1], emp.nombre)
    escribir(t_datos.rows[1].cells[1], emp.rfc)
    marcar_casillas(doc, t_datos.rows[2].cells[1], emp.es_estatal)

    # Renglones 3 a 6: hasta 4 claves presupuestales.
    for i, fila in enumerate(range(3, 3 + datos.MAX_CLAVES)):
        escribir(t_datos.rows[fila].cells[1], emp.claves[i] if i < len(emp.claves) else "")

    escribir(t_datos.rows[7].cells[1], emp.correo)
    escribir(t_datos.rows[8].cells[1], emp.telefono)

    anexar(t_centros.rows[1].cells[0], emp.ct_actual_nombre)
    anexar(t_centros.rows[2].cells[0], emp.ct_actual_clave)
    anexar(t_centros.rows[1].cells[1], emp.ct_solicitado_nombre)
    anexar(t_centros.rows[2].cells[1], emp.ct_solicitado_clave)

    # Pies de firma. Quien libera es el titular del centro actual y quien recibe
    # el del solicitado: sirve igual para los que entran a la DFC y los que salen.
    parrafo_antes(t_solicitante.rows[0].cells[0].paragraphs[0], emp.nombre)
    agregados = 1

    for celda, d in zip(t_firmas.rows[0].cells, (emp.libera, emp.recibe)):
        if d.titular:
            parrafo_antes(celda.paragraphs[0], d.cargo, bold=False)
            parrafo_antes(celda.paragraphs[0], d.titular)
    agregados += 2      # libera y recibe van lado a lado: suman alto una sola vez

    recuperar_renglones(doc, agregados)
    doc.save(destino)            # destino: ruta en disco o un buffer en memoria


def generar_bytes(emp) -> bytes:
    """El mismo formato, pero en memoria: lo usa la app para el boton de descarga."""
    buf = io.BytesIO()
    generar(emp, buf)
    return buf.getvalue()

def nombre_archivo(emp) -> str:
    seguro = "".join(c for c in emp.nombre if c.isalnum() or c == " ").replace(" ", "_")
    return f"{int(emp.n):02d}_{seguro[:40]}_{emp.rfc}.docx"

def main():
    todos = "--todos" in sys.argv
    empleados = datos.cargar(datos.abrir_libro())

    generados, omitidos = [], []
    for emp in empleados:
        problemas = emp.problemas()
        if problemas and not todos:
            omitidos.append((emp, problemas))
            continue
        SALIDA.mkdir(exist_ok=True)
        ruta = SALIDA / nombre_archivo(emp)
        generar(emp, str(ruta))
        generados.append(ruta)
        aviso = f"   <-- INCOMPLETO: {'; '.join(problemas)}" if problemas else ""
        print(f"  {ruta.name}{aviso}")

    print(f"\nGenerados: {len(generados)}")
    if omitidos:
        print(f"Omitidos por datos faltantes: {len(omitidos)} "
              f"(corre con --todos para generarlos con los huecos en blanco)")
        for emp, problemas in omitidos:
            print(f"  {emp.n:>2} {emp.nombre[:34]:36} {'; '.join(problemas)}")

if __name__ == "__main__":
    main()
