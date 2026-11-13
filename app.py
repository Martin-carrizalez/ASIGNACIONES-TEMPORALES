#!/usr/bin/env python3
"""Validación de datos para la asignación temporal — Dirección de Formación Continua.

Cada trabajador entra con su RFC, revisa los datos con los que se va a generar su
formato y contesta una de tres cosas: que están correctos, que hay un error, o que
no desea continuar. Todo queda con fecha y hora.

    streamlit run app.py
"""

import dataclasses
import html
from datetime import datetime
from pathlib import Path

import streamlit as st

import datos
import generar
import respuestas

LOGO = Path(__file__).parent / "assets" / "logo_rhdfc.png"
TITULO = "Asignación temporal"
SUBTITULO = "Validación de datos"
AREA = "Dirección de Formación Continua"

st.set_page_config(page_title=f"{TITULO} · {SUBTITULO}", page_icon="📄",
                   layout="centered", initial_sidebar_state="expanded")

# Los datos de nomina se muestran como ficha de texto normal, no como casillas
# deshabilitadas (esas salen en gris claro y casi no se leen).
# Los colores se heredan del tema, asi se ve bien en claro y en oscuro.
ESTILO = """
<style>
.ficha {display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:14px 28px; margin:6px 0 14px;}
.ficha .ancho {grid-column:1/-1;}
.ficha .etq {font-size:.74rem; letter-spacing:.05em; text-transform:uppercase; opacity:.62; margin-bottom:2px;}
.ficha .val {font-size:1.05rem; font-weight:600; line-height:1.35; word-break:break-word;}
.ficha .val.mono {font-family:ui-monospace,Menlo,Consolas,monospace; font-size:1rem;}
.ficha .sub {font-size:.9rem; opacity:.75; font-family:ui-monospace,Menlo,Consolas,monospace;}
.ficha .ct {border-left:4px solid #e5007d; padding-left:12px;}
</style>
"""


def _secretos():
    # st.secrets truena si no hay archivo de secretos; en ese caso datos.py
    # usa las variables de entorno SHEET_ID y GOOGLE_SERVICE_ACCOUNT_JSON.
    try:
        _ = st.secrets["sheet_id"]
        return st.secrets
    except Exception:
        return None


@st.cache_resource
def libro():
    return datos.abrir_libro(_secretos())


@st.cache_data(ttl=300)          # relee el Sheet cada 5 minutos
def cargar():
    return datos.cargar(libro())


def almacen():
    return respuestas.Almacen(libro=libro())


def _e(valor) -> str:
    # Todo lo que viene del Sheet se escapa antes de meterlo al HTML de la ficha.
    return html.escape(str(valor or "—"))


def ficha_nomina(emp):
    """Datos de nomina en texto grande y legible, solo lectura."""
    claves = "<br>".join(_e(c) for c in emp.claves) or "—"
    st.markdown(f"""
<div class="ficha">
  <div><div class="etq">RFC</div><div class="val mono">{_e(emp.rfc)}</div></div>
  <div><div class="etq">Sostenimiento</div><div class="val">{_e(emp.sostenimiento)}</div></div>
  <div class="ancho"><div class="etq">Clave(s) presupuestal(es)</div><div class="val mono">{claves}</div></div>
  <div class="ct"><div class="etq">Centro de trabajo actual</div>
       <div class="val">{_e(emp.ct_actual_nombre)}</div><div class="sub">{_e(emp.ct_actual_clave)}</div></div>
  <div class="ct"><div class="etq">Centro de trabajo solicitado</div>
       <div class="val">{_e(emp.ct_solicitado_nombre)}</div><div class="sub">{_e(emp.ct_solicitado_clave)}</div></div>
</div>
""", unsafe_allow_html=True)


def barra_lateral():
    with st.sidebar:
        if LOGO.exists():              # si falta la imagen la app sigue sin logo
            st.image(str(LOGO))
        st.markdown(f"### {AREA}")
        st.caption("Recursos Humanos")
        st.divider()
        st.markdown("**Cómo funciona**")
        st.markdown(
            "1. Entra con tu RFC.\n"
            "2. Revisa tus datos.\n"
            "3. Corrige tu nombre, correo o teléfono si hace falta.\n"
            "4. Confirma que están correctos, o reporta el error.\n"
            "5. Descarga tu formato, imprímelo y recaba las firmas.")
        st.divider()
        st.markdown("**Es de libre elección**")
        st.caption(f"Nadie está obligado a continuar en la {AREA}. "
                   "Si decides no continuar, tu adscripción no se mueve.")
        st.divider()
        st.caption("¿Un dato de nómina no coincide? No lo corrijas por tu cuenta: "
                   "repórtalo con el botón «Hay un error en mis datos».")


def fecha_del_formato(fecha_hora: str) -> str:
    """'2026-11-12 19:22:13' -> '12 de noviembre de 2026'."""
    try:
        return generar.fecha_larga(datetime.strptime(fecha_hora[:10], "%Y-%m-%d").date())
    except ValueError:
        return generar.fecha_larga()


def boton_descarga(emp, nombre, correo, telefono, fecha_hora):
    """Formato Word listo para imprimir, ya con las correcciones que hizo la persona.
    Solo se ofrece si el expediente esta completo; si falta algo (por ejemplo el
    titular que libera), Recursos Humanos lo entrega cuando se complete.
    La fecha del formato es el dia en que la persona acepto (fecha_hora de su respuesta)."""
    final = dataclasses.replace(emp, nombre=nombre.strip() or emp.nombre,
                                correo=correo.strip() or emp.correo,
                                telefono=telefono.strip() or emp.telefono)
    if final.problemas():
        st.info("Tu formato todavía tiene un dato pendiente de completar. "
                f"Recursos Humanos de la {AREA} te lo entrega en cuanto esté listo.")
        return
    st.download_button(
        "⬇️ Descargar mi formato en Word", data=generar.generar_bytes(final, fecha_del_formato(fecha_hora)),
        file_name=generar.nombre_archivo(final), key=f"dl_{emp.n}",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    st.caption("Imprímelo, fírmalo, recaba la firma de quien libera el recurso y "
               f"entrégalo en Recursos Humanos de la {AREA}.")


# Campos que se limpian al volver a la pantalla de inicio, para que la siguiente
# persona que use el mismo equipo no vea lo que escribio la anterior.
_CAMPOS_SESION = ("rfc", "nom_", "cor_", "tel_", "obs_", "confirmar_")

MENSAJE_FINAL = {
    "acepta": "Tu aceptación quedó registrada. Para volver a descargar tu formato, "
              "entra de nuevo con tu RFC.",
    "declina": "Quedó registrado que no deseas continuar. Tu adscripción no se mueve.",
}


def volver_al_inicio(mensaje=None):
    """Regresa a la pantalla de inicio con la casilla del RFC vacia. El mensaje se
    muestra una vez arriba de esa casilla."""
    st.session_state["_volver"] = True
    if mensaje:
        st.session_state["_mensaje"] = mensaje
    st.rerun()


def _limpiar_si_toca():
    # Se hace antes de dibujar la casilla del RFC: Streamlit no deja cambiar el
    # valor de un campo despues de dibujarlo.
    if st.session_state.pop("_volver", False):
        for k in list(st.session_state):
            if k.startswith(_CAMPOS_SESION) and k != "rfc":
                del st.session_state[k]
        # El RFC se vacia asignandole "" y no borrandolo: si solo se borra, el
        # navegador sigue mostrando el texto anterior en la casilla.
        st.session_state["rfc"] = ""


def registrar(store, base, decision):
    """Guarda la respuesta, salvo que la solicitud ya este cerrada: cubre el doble
    clic y el caso de tener la app abierta en dos pestañas.

    Aceptar o declinar son decisiones finales: guardan y regresan al inicio.
    Reportar un error no: se queda en la misma pantalla mostrando el reporte,
    porque la solicitud sigue abierta hasta que RH lo solvente."""
    previa = store.estado_de(base["rfc"], base["n"])
    if not (previa and previa["decision"] in respuestas.FINALES):
        store.guardar({**base, "decision": decision})
    if decision in respuestas.FINALES:
        volver_al_inicio(MENSAJE_FINAL[decision])
    st.rerun()


def mostrar_cerrada(emp, resp):
    """Solicitud ya aceptada o declinada: solo lectura. No hay forma de editar,
    volver a contestar ni cambiar de decision desde la app."""
    if resp["decision"] == "declina":
        st.info(f"El {resp['fecha_hora']} registraste que **no deseas continuar** en la "
                f"{AREA}. Tu respuesta quedó registrada y ya no se puede modificar.")
    else:
        st.success(f"**Aceptaste esta asignación el {resp['fecha_hora']}.** "
                   "Tu respuesta quedó registrada y ya no se puede modificar.")
        with st.container(border=True):
            st.markdown("#### Datos que aceptaste")
            ficha_nomina(emp)
            st.markdown(f"""
<div class="ficha">
  <div class="ancho"><div class="etq">Nombre</div><div class="val">{_e(resp['nombre_corregido'])}</div></div>
  <div><div class="etq">Correo electrónico</div><div class="val">{_e(resp['correo_corregido'])}</div></div>
  <div><div class="etq">Teléfono</div><div class="val">{_e(resp['telefono_corregido'])}</div></div>
</div>
""", unsafe_allow_html=True)
        # El Word sale siempre con los datos que la persona acepto, no editables.
        boton_descarga(emp, str(resp["nombre_corregido"]), str(resp["correo_corregido"]),
                       str(resp["telefono_corregido"]), str(resp["fecha_hora"]))
    st.caption(f"Si necesitas cambiar tu respuesta, acude a Recursos Humanos de la {AREA}.")
    if st.button("Salir", key=f"salir_{emp.n}"):
        volver_al_inicio()


def mostrar_solicitud(emp, store):
    previa = store.estado_de(emp.rfc, emp.n)
    if previa and previa["decision"] in respuestas.FINALES:
        mostrar_cerrada(emp, previa)
        return
    if previa:      # solo ha reportado un error: la solicitud sigue abierta
        st.warning(
            f"El {previa['fecha_hora']} reportaste un error: «{previa['observaciones']}». "
            "Cuando Recursos Humanos lo corrija verás aquí el dato actualizado y "
            "podrás confirmar.")

    with st.container(border=True):
        st.markdown("#### Tus datos de nómina")
        st.caption("No se editan aquí. Si alguno no coincide, repórtalo abajo y se "
                   "revisa contra nómina antes de generar tu formato.")
        ficha_nomina(emp)

    with st.container(border=True):
        st.markdown("#### Datos que sí puedes corregir")
        nombre = st.text_input("Nombre completo, como debe aparecer en el documento",
                               value=emp.nombre, key=f"nom_{emp.n}")
        c_correo, c_tel = st.columns(2)
        with c_correo:
            correo = st.text_input("Correo electrónico", value=emp.correo, key=f"cor_{emp.n}")
        with c_tel:
            telefono = st.text_input("Teléfono", value=emp.telefono, key=f"tel_{emp.n}")

    observaciones = st.text_area(
        "Observaciones (obligatorio si reportas un error)",
        placeholder="Ejemplo: mi clave presupuestal no coincide con la de mi talón de pago.",
        key=f"obs_{emp.n}")

    st.markdown("#### ¿Qué deseas hacer?")
    st.caption("Aceptar y no continuar son respuestas definitivas: una vez enviadas "
               "no se pueden cambiar desde aquí. Revisa bien antes de confirmar.")

    base = dict(n=emp.n, rfc=emp.rfc, nombre_en_relacion=emp.nombre,
                nombre_corregido=nombre, correo_corregido=correo,
                telefono_corregido=telefono, observaciones=observaciones)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✅ Mis datos son correctos y acepto la asignación",
                     type="primary", use_container_width=True, key=f"ok_{emp.n}"):
            registrar(store, base, "acepta")
    with c2:
        if st.button("✏️ Hay un error en mis datos",
                     use_container_width=True, key=f"err_{emp.n}"):
            if not observaciones.strip():
                st.error("Escribe en observaciones cuál es el dato equivocado.")
            else:
                registrar(store, base, "error")

    st.divider()
    st.caption(
        f"Continuar en la {AREA} es de libre elección: nadie está obligado. "
        "Si decides no continuar, tu adscripción no se mueve.")

    # Declinar es definitivo, por eso va en dos pasos.
    if st.session_state.get(f"confirmar_{emp.n}"):
        st.warning(
            f"¿Confirmas que **no deseas continuar** en la {AREA}? "
            "Con esto no se tramita tu asignación temporal y no podrás cambiarlo aquí.")
        d1, d2 = st.columns(2)
        with d1:
            if st.button("Sí, confirmo que no continúo",
                         use_container_width=True, key=f"condec_{emp.n}"):
                st.session_state[f"confirmar_{emp.n}"] = False
                registrar(store, base, "declina")
        with d2:
            if st.button("Cancelar", use_container_width=True, key=f"cancel_{emp.n}"):
                st.session_state[f"confirmar_{emp.n}"] = False
                st.rerun()
    else:
        if st.button(f"🚫 No deseo continuar en la {AREA}", key=f"dec_{emp.n}"):
            st.session_state[f"confirmar_{emp.n}"] = True
            st.rerun()


def main():
    st.markdown(ESTILO, unsafe_allow_html=True)
    barra_lateral()
    st.title(TITULO)
    st.caption(f"{SUBTITULO} · {AREA}")
    st.write("Antes de generar tu formato necesitamos que revises que tus datos "
             "estén correctos. Entra con tu RFC a 13 caracteres.")

    store = almacen()

    _limpiar_si_toca()
    mensaje = st.session_state.pop("_mensaje", None)
    if mensaje:
        st.success(mensaje)

    rfc = st.text_input("RFC (con homoclave)", max_chars=13, key="rfc",
                        placeholder="AAAA000000AAA").strip().upper()
    if not rfc:
        st.stop()

    # Los mensajes de datos.py solo nombran pestañas y encabezados, nunca datos
    # de personas, por eso se pueden mostrar tal cual.
    try:
        empleados = cargar()
    except RuntimeError as e:
        st.error(f"No pude leer la relación: {e}")
        st.stop()

    solicitudes = [e for e in empleados if e.rfc.upper() == rfc]
    if not solicitudes:
        st.error("Ese RFC no está en la relación de solicitudes. "
                 "Revísalo; si está bien escrito, avisa a Recursos Humanos de la "
                 f"{AREA}.")
        st.stop()

    st.success(f"Hola, **{solicitudes[0].nombre}**.")

    # Una persona puede tener mas de una solicitud (por ejemplo, dos plazas en dos
    # centros de trabajo distintos). Cada una se valida por separado.
    if len(solicitudes) > 1:
        st.info(f"Tienes {len(solicitudes)} solicitudes y cada una se valida aparte.")
        etiquetas = [f"Solicitud {e.n} — {e.ct_actual_nombre[:38]}" for e in solicitudes]
        for pestana, emp in zip(st.tabs(etiquetas), solicitudes):
            with pestana:
                mostrar_solicitud(emp, store)
    else:
        mostrar_solicitud(solicitudes[0], store)


if __name__ == "__main__":
    main()
