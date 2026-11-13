#!/usr/bin/env python3
"""Genera un FORMATO DE ASIGNACION TEMPORAL por empleado.

Llena la plantilla original sin reconstruirla: la abre y escribe sobre sus celdas,
asi conserva los logos del pie, los margenes, las fuentes y la nota legal.

Lee los datos del Google Sheet (variables SHEET_ID y GOOGLE_SERVICE_ACCOUNT_JSON).

    python3 generar.py                 # genera solo los expedientes sin problemas
    python3 generar.py --todos         # genera tambien los incompletos, con huecos
"""

import io
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docx.text.paragraph import Paragraph

import datos

BASE = Path(__file__).parent
PLANTILLA = BASE / "templates" / "FORMATO_ASIGNACION_TEMPORAL_2026.docx"
SALIDA = BASE / "salida"

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

def fecha_larga(d=None) -> str:
    """'12 de noviembre de 2026'. Sin argumento, la fecha de hoy en hora de Mexico."""
    d = d or datetime.now(ZoneInfo("America/Mexico_City")).date()
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"

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

def reemplazar_texto(parrafo, texto, tam=TAM_PIE, bold=True):
    """Cambia todo el texto de un parrafo conservando su alineacion."""
    for r in list(parrafo.runs):
        r._element.getparent().remove(r._element)
    _nuevo_run(parrafo, texto, tam=tam, bold=bold)

def parrafo_despues(parrafo, texto, tam=TAM_PIE, bold=True):
    """Agrega una linea centrada debajo de un parrafo."""
    nuevo = OxmlElement("w:p")
    parrafo._p.addnext(nuevo)
    np = Paragraph(nuevo, parrafo._parent)
    np.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _nuevo_run(np, texto, tam=tam, bold=bold)

def poner_fecha(doc, fecha: str):
    """Sustituye la raya de 'Fecha: ______' por la fecha escrita."""
    for p in doc.paragraphs:
        if "Fecha:" not in p.text:
            continue
        rayas = [r for r in p.runs if "_" in r.text]
        if not rayas:
            raise RuntimeError("No encontre la raya de la fecha en la plantilla.")
        rayas[0].text = fecha
        for r in rayas[1:]:
            r._element.getparent().remove(r._element)
        return
    raise RuntimeError("No encontre el renglon 'Fecha:' en la plantilla.")

def _es_blanco(el) -> bool:
    return el.tag == qn("w:p") and not "".join(el.itertext()).strip()

def _fijar_al_flujo(tabla):
    """La tabla de la firma del solicitante es 'flotante' en la plantilla: no
    ocupa lugar propio y los renglones en blanco de abajo le reservaban el
    espacio. Se fija al flujo normal (centrada, como estaba) para que el
    espacio sea predecible y se pueda recortar el relleno sin que el texto de
    abajo se le suba encima."""
    tblPr = tabla._tbl.tblPr
    flotante = tblPr.find(qn("w:tblpPr"))
    if flotante is not None:
        tblPr.remove(flotante)
    if tblPr.find(qn("w:jc")) is None:
        jc = OxmlElement("w:jc")
        jc.set(qn("w:val"), "center")
        tblPr.append(jc)

def _quitar_blanco_junto_a(cuerpo, texto, despues=False):
    """Quita UN renglon en blanco pegado (antes o despues) al parrafo que
    contiene texto. Si ahi no hay renglon en blanco, no hace nada."""
    for i, c in enumerate(cuerpo):
        if c.tag == qn("w:p") and texto in "".join(c.itertext()):
            j = i + 1 if despues else i - 1
            if 0 <= j < len(cuerpo) and _es_blanco(cuerpo[j]):
                cuerpo[j].getparent().remove(cuerpo[j])
            return

def compactar(doc):
    """La plantilla original ocupa dos hojas: la nota del pie cae sola en la
    segunda. Para que todo quepa en una hoja se fija la tabla del solicitante y
    se recortan renglones en blanco que solo eran relleno. El espacio donde se
    firma no se toca:
      - entre la firma del solicitante y 'Libera el recurso' habia 5: queda 1
      - el que estaba despues del titulo
      - el que estaba entre 'Es importante mencionar...' y 'Atentamente'"""
    _fijar_al_flujo(doc.tables[2])
    cuerpo = list(doc.element.body.iterchildren())
    tablas = [i for i, c in enumerate(cuerpo) if c.tag == qn("w:tbl")]
    hueco = []
    for c in cuerpo[tablas[2] + 1:]:
        if "Libera el recurso" in "".join(c.itertext()):
            break
        if _es_blanco(c):
            hueco.append(c)
    for c in hueco[1:]:
        c.getparent().remove(c)
    _quitar_blanco_junto_a(cuerpo, "Cambio de Adscripción", despues=True)
    _quitar_blanco_junto_a(cuerpo, "Atentamente")

def _casillas(doc) -> dict:
    """Las cuatro casillas redondeadas, por nombre. Son figuras con cuadro de texto
    y aparecen en la plantilla en este orden: la figura 0 es el letrero 'Datos del
    personal' y la 5 el de 'Descripcion del movimiento'."""
    figuras = [a for a in doc.element.body.iter() if a.tag.endswith("}anchor")]
    if len(figuras) != 6:
        raise RuntimeError(
            f"Se esperaban 6 figuras en la plantilla y hay {len(figuras)}. "
            "Cambio la plantilla: hay que volver a mapear las casillas.")
    return dict(zip(("estatal", "federal", "temporal", "definitivo"), figuras[1:5]))

def _cruz(figura):
    """Escribe la X DENTRO de la casilla.

    Word guarda cada figura dos veces (mc:Choice moderno y mc:Fallback VML): se
    marca en las dos. El color negro va explicito porque la casilla 'Estatal' trae
    en su estilo letra blanca: sin esto la X se escribe pero no se ve."""
    alterno = figura
    while not alterno.tag.endswith("}AlternateContent"):
        alterno = alterno.getparent()
    for caja in [t for t in alterno.iter() if t.tag.endswith("txbxContent")]:
        p = caja.find(qn("w:p"))
        par = Paragraph(p, None)
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        par.paragraph_format.space_after = Pt(0)
        r = _nuevo_run(par, "X", tam=Pt(10), bold=True)
        r.font.color.rgb = RGBColor(0, 0, 0)

def marcar_casillas(doc, es_estatal):
    casillas = _casillas(doc)
    _cruz(casillas["estatal" if es_estatal else "federal"])
    _cruz(casillas["temporal"])      # todas son asignacion temporal

# ---------------------------------------------------------------- generacion

def generar(emp, destino, fecha=None):
    """destino: ruta en disco o buffer en memoria. fecha: texto que va en 'Fecha:';
    si no se da, la de hoy."""
    doc = Document(str(PLANTILLA))
    compactar(doc)
    poner_fecha(doc, fecha or fecha_larga())

    t_datos, t_centros, t_solicitante, t_firmas = doc.tables[:4]

    escribir(t_datos.rows[0].cells[1], emp.nombre)
    escribir(t_datos.rows[1].cells[1], emp.rfc)
    marcar_casillas(doc, emp.es_estatal)

    # Renglones 3 a 6: hasta 4 claves presupuestales.
    for i, fila in enumerate(range(3, 3 + datos.MAX_CLAVES)):
        escribir(t_datos.rows[fila].cells[1], emp.claves[i] if i < len(emp.claves) else "")

    escribir(t_datos.rows[7].cells[1], emp.correo)
    escribir(t_datos.rows[8].cells[1], emp.telefono)

    anexar(t_centros.rows[1].cells[0], emp.ct_actual_nombre)
    anexar(t_centros.rows[2].cells[0], emp.ct_actual_clave)
    anexar(t_centros.rows[1].cells[1], emp.ct_solicitado_nombre)
    anexar(t_centros.rows[2].cells[1], emp.ct_solicitado_clave)

    # Pies de firma. Las leyendas genericas del formato ("Nombre y firma de la
    # persona solicitante", "Nombre, puesto y firma de...") se SUSTITUYEN por el
    # nombre real; no se dejan las dos cosas. Nombre y cargo van con el mismo
    # formato: mayusculas y negritas. La leyenda "Autorizo el movimiento..." del
    # solicitante se conserva porque es su declaracion.
    reemplazar_texto(t_solicitante.rows[0].cells[0].paragraphs[0], emp.nombre.upper())

    # Quien libera es el titular del centro actual y quien recibe el del solicitado:
    # sirve igual para los que entran a la DFC y los que salen.
    for celda, d in zip(t_firmas.rows[0].cells, (emp.libera, emp.recibe)):
        if d.titular:                 # sin titular se deja la leyenda del formato
            pie = celda.paragraphs[0]
            reemplazar_texto(pie, d.titular.upper())
            parrafo_despues(pie, d.cargo.upper())

    doc.save(destino)


def generar_bytes(emp, fecha=None) -> bytes:
    """El mismo formato, pero en memoria: lo usa la app para el boton de descarga."""
    buf = io.BytesIO()
    generar(emp, buf, fecha)
    return buf.getvalue()

def a_pdf(docx_bytes: bytes) -> bytes:
    """Convierte el Word a PDF con LibreOffice y le quita el permiso de edicion.

    Al empleado se le entrega SOLO el PDF: un Word lo puede editar en cualquier
    computadora y se perderia el control sobre los datos de nomina."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice no esta instalado (en Streamlit Cloud va en packages.txt).")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        entrada = tmp / "formato.docx"
        entrada.write_bytes(docx_bytes)
        # Perfil propio por conversion: si dos personas descargan al mismo tiempo,
        # LibreOffice no se traba peleando por el mismo perfil.
        perfil = (tmp / "perfil").as_uri()
        subprocess.run(
            [soffice, f"-env:UserInstallation={perfil}", "--headless",
             "--convert-to", "pdf", "--outdir", str(tmp), str(entrada)],
            check=True, capture_output=True, timeout=180)
        salida = tmp / "formato.pdf"
        if not salida.exists():
            raise RuntimeError("LibreOffice no genero el PDF.")
        return proteger(salida.read_bytes())


def proteger(pdf_bytes: bytes) -> bytes:
    """Cifra el PDF dejando solo el permiso de imprimir: abre sin contraseña, pero
    los lectores de PDF no permiten modificarlo, copiar texto ni llenarlo. La
    contraseña de propietario es aleatoria y no se guarda en ningun lado."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.constants import UserAccessPermissions as P
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    w.encrypt(user_password="", owner_password=secrets.token_hex(16),
              permissions_flag=P.PRINT | P.PRINT_TO_REPRESENTATION)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def generar_pdf(emp, fecha=None) -> bytes:
    """El formato que se le entrega al empleado: PDF protegido, nunca el Word."""
    return a_pdf(generar_bytes(emp, fecha))


def nombre_archivo(emp, extension="docx") -> str:
    seguro = "".join(c for c in emp.nombre if c.isalnum() or c == " ").replace(" ", "_")
    return f"{int(emp.n):02d}_{seguro[:40]}_{emp.rfc}.{extension}"

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
