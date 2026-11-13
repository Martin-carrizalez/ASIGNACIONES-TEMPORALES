#!/usr/bin/env python3
"""Validación de datos para la asignación temporal — Dirección de Formación Continua.

Cada trabajador entra con su RFC, revisa los datos con los que se va a generar su
formato y contesta una de tres cosas: que están correctos, que hay un error, o que
no desea continuar. Todo queda con fecha y hora.

    streamlit run app.py
"""

import dataclasses

import streamlit as st

import datos
import generar
import respuestas

TITULO = "Validación de datos — Asignación temporal"
AREA = "Dirección de Formación Continua"

st.set_page_config(page_title=TITULO, page_icon="📄", layout="centered")


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


def campo_bloqueado(etiqueta, valor, n):
    # La llave lleva el numero de solicitud: una persona puede tener dos y los
    # campos se repiten con el mismo valor (el RFC, por ejemplo).
    st.text_input(etiqueta, value=valor or "—", disabled=True,
                  key=f"ro_{n}_{etiqueta}")


def boton_descarga(emp, nombre, correo, telefono):
    """Formato Word listo para imprimir, ya con las correcciones que hizo la persona.
    Solo se ofrece si el expediente esta completo; si falta algo (por ejemplo el
    titular que libera), Recursos Humanos lo entrega cuando se complete."""
    final = dataclasses.replace(emp, nombre=nombre.strip() or emp.nombre,
                                correo=correo.strip() or emp.correo,
                                telefono=telefono.strip() or emp.telefono)
    if final.problemas():
        st.info("Tu formato todavía tiene un dato pendiente de completar. "
                f"Recursos Humanos de la {AREA} te lo entrega en cuanto esté listo.")
        return
    st.download_button(
        "⬇️ Descargar mi formato en Word", data=generar.generar_bytes(final),
        file_name=generar.nombre_archivo(final), key=f"dl_{emp.n}",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    st.caption("Imprímelo, fírmalo, recaba la firma de quien libera el recurso y "
               f"entrégalo en Recursos Humanos de la {AREA}.")


def mostrar_solicitud(emp, store):
    previa = store.ultima_de(emp.rfc, emp.n)
    if previa:
        st.success(
            f"Ya contestaste esta solicitud el {previa['fecha_hora']}: "
            f"**{respuestas.DECISIONES.get(previa['decision'], previa['decision'])}**. "
            "Si te equivocaste, puedes volver a contestar y se toma la última.")
        if previa["decision"] == "acepta":
            boton_descarga(emp, str(previa["nombre_corregido"]),
                           str(previa["correo_corregido"]), str(previa["telefono_corregido"]))

    st.subheader("Datos que no puedes editar aquí")
    st.caption(
        "Estos vienen de nómina. Si alguno no coincide, no lo corrijas por tu cuenta: "
        "repórtalo abajo y se revisa contra nómina antes de generar el formato.")
    col1, col2 = st.columns(2)
    with col1:
        campo_bloqueado("RFC", emp.rfc, emp.n)
        campo_bloqueado("Sostenimiento", emp.sostenimiento, emp.n)
        campo_bloqueado("Centro de trabajo actual", emp.ct_actual_nombre, emp.n)
        campo_bloqueado("Clave del centro actual", emp.ct_actual_clave, emp.n)
    with col2:
        campo_bloqueado("Claves presupuestales", " | ".join(emp.claves), emp.n)
        campo_bloqueado("Centro de trabajo solicitado", emp.ct_solicitado_nombre, emp.n)
        campo_bloqueado("Clave del centro solicitado", emp.ct_solicitado_clave, emp.n)

    st.subheader("Datos que sí puedes corregir")
    nombre = st.text_input("Nombre completo, como debe aparecer en el documento",
                           value=emp.nombre, key=f"nom_{emp.n}")
    correo = st.text_input("Correo electrónico", value=emp.correo, key=f"cor_{emp.n}")
    telefono = st.text_input("Teléfono", value=emp.telefono, key=f"tel_{emp.n}")

    observaciones = st.text_area(
        "Observaciones (obligatorio si reportas un error)",
        placeholder="Ejemplo: mi clave presupuestal no coincide con la de mi talón de pago.",
        key=f"obs_{emp.n}")

    st.divider()
    st.write("**¿Qué deseas hacer?**")

    base = dict(n=emp.n, rfc=emp.rfc, nombre_en_relacion=emp.nombre,
                nombre_corregido=nombre, correo_corregido=correo,
                telefono_corregido=telefono, observaciones=observaciones)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✅ Mis datos son correctos y acepto la asignación",
                     use_container_width=True, key=f"ok_{emp.n}"):
            guardado = store.guardar({**base, "decision": "acepta"})
            st.session_state[f"acuse_{emp.n}"] = ("acepta", guardado["fecha_hora"], nombre, correo, telefono)
            st.rerun()
    with c2:
        if st.button("✏️ Hay un error en mis datos",
                     use_container_width=True, key=f"err_{emp.n}"):
            if not observaciones.strip():
                st.error("Escribe en observaciones cuál es el dato equivocado.")
            else:
                guardado = store.guardar({**base, "decision": "error"})
                st.session_state[f"acuse_{emp.n}"] = ("error", guardado["fecha_hora"], nombre, correo, telefono)
                st.rerun()

    st.divider()
    st.caption(
        f"Continuar en la {AREA} es de libre elección: nadie está obligado. "
        "Si decides no continuar, tu adscripción no se mueve.")

    # Declinar es la única acción que no se puede deshacer sola, por eso va en dos pasos.
    if st.session_state.get(f"confirmar_{emp.n}"):
        st.warning(
            f"¿Confirmas que **no deseas continuar** en la {AREA}? "
            "Con esto no se tramita tu asignación temporal.")
        d1, d2 = st.columns(2)
        with d1:
            if st.button("Sí, confirmo", type="primary",
                         use_container_width=True, key=f"condec_{emp.n}"):
                guardado = store.guardar({**base, "decision": "declina"})
                st.session_state[f"acuse_{emp.n}"] = ("declina", guardado["fecha_hora"], nombre, correo, telefono)
                st.session_state[f"confirmar_{emp.n}"] = False
                st.rerun()
        with d2:
            if st.button("Cancelar", use_container_width=True, key=f"cancel_{emp.n}"):
                st.session_state[f"confirmar_{emp.n}"] = False
                st.rerun()
    else:
        if st.button(f"🚫 No deseo continuar en la {AREA}", key=f"dec_{emp.n}"):
            st.session_state[f"confirmar_{emp.n}"] = True
            st.rerun()


def mostrar_acuse(emp):
    decision, cuando, nombre, correo, telefono = st.session_state[f"acuse_{emp.n}"]
    st.success(f"**Acuse registrado el {cuando}**")
    st.write({
        "acepta": "Quedó registrado que tus datos son correctos y que aceptas la asignación temporal.",
        "error": "Quedó registrado el error que reportaste. Se revisa y se te vuelve a mostrar el dato corregido.",
        "declina": f"Quedó registrado que no deseas continuar en la {AREA}. Tu adscripción no se mueve.",
    }[decision])
    if decision == "acepta":
        boton_descarga(emp, nombre, correo, telefono)
    st.caption("Toma captura de pantalla de este acuse para tu control.")
    if st.button("Volver a revisar mis datos", key=f"volver_{emp.n}"):
        del st.session_state[f"acuse_{emp.n}"]
        st.rerun()


def main():
    st.title(TITULO)
    st.write(
        f"Antes de generar tu formato de asignación temporal necesitamos que revises "
        f"que tus datos estén correctos. Entra con tu RFC a 13 caracteres."
    )

    store = almacen()

    rfc = st.text_input("RFC (con homoclave)", max_chars=13,
                        placeholder="AAAA000000AAA").strip().upper()
    if not rfc:
        st.stop()

    solicitudes = [e for e in cargar() if e.rfc.upper() == rfc]
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
                if f"acuse_{emp.n}" in st.session_state:
                    mostrar_acuse(emp)
                else:
                    mostrar_solicitud(emp, store)
    else:
        emp = solicitudes[0]
        if f"acuse_{emp.n}" in st.session_state:
            mostrar_acuse(emp)
        else:
            mostrar_solicitud(emp, store)


if __name__ == "__main__":
    main()
