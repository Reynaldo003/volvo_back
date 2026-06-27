CHECKLIST_ENTREGA = [
    {
        "titulo": "EXPLICACIÓN TÉCNICA AL CLIENTE",
        "items": [
            ("explicar_falla_detectada", "Explicar claramente cuál era la falla detectada"),
            ("explicar_causa_raiz", "Explicar la causa raíz encontrada"),
            ("mostrar_piezas_reemplazadas", "Mostrar piezas reemplazadas si aplica"),
            ("explicar_trabajos_realizados", "Explicar los trabajos realizados punto por punto"),
            ("explicar_pruebas_realizadas", "Explicar pruebas realizadas para validar reparación"),
            ("informar_garantias_aplicables", "Informar garantías aplicables"),
            ("explicar_recomendaciones_futuras", "Explicar recomendaciones futuras o mantenimiento preventivo"),
        ],
    },
    {
        "titulo": "CONFIRMACIÓN DE COMPRENSIÓN DEL CLIENTE",
        "items": [
            ("preguntar_cliente_dudas", "Preguntar al cliente si tiene dudas"),
            ("confirmar_cliente_entendio", "Confirmar que el cliente entendió el trabajo realizado"),
            ("validacion_verbal_conformidad", "Solicitar validación verbal de conformidad"),
        ],
    },
    {
        "titulo": "REVISIÓN CONJUNTA DE ENTREGA",
        "items": [
            ("revisar_fisicamente_vehiculo", "Revisar físicamente el vehículo con el cliente"),
            ("prueba_ruta_cliente_entrega", "Realizar prueba de ruta con el cliente si aplica"),
            ("validar_estado_estetico", "Validar estado estético del vehículo"),
            ("confirmar_sistemas_intervenidos", "Confirmar funcionamiento de sistemas intervenidos"),
            ("entregar_refacciones_reemplazadas", "Entregar refacciones reemplazadas si aplica"),
        ],
    },
    {
        "titulo": "DOCUMENTACIÓN FINAL",
        "items": [
            ("entregar_factura_orden_final", "Entregar factura y orden de servicio final"),
            ("entregar_desglose_trabajos_costos", "Entregar desglose de trabajos y costos"),
            ("obtener_firma_conformidad", "Obtener firma de conformidad de los trabajos realizados"),
        ],
    },
]

CHECKLIST_ENTREGA_IDS = {
    item_id
    for seccion in CHECKLIST_ENTREGA
    for item_id, _descripcion in seccion["items"]
}

CHECKLIST_ENTREGA_MAP = {
    item_id: descripcion
    for seccion in CHECKLIST_ENTREGA
    for item_id, descripcion in seccion["items"]
}

# Estos puntos son el candado real del proceso: no deben quedar en N/A ni observación.
# Cumple el requisito de que la explicación al cliente sea obligatoria y medible.
ENTREGA_OBLIGATORIOS_OK = {
    "explicar_falla_detectada",
    "explicar_causa_raiz",
    "explicar_trabajos_realizados",
    "explicar_pruebas_realizadas",
    "informar_garantias_aplicables",
    "explicar_recomendaciones_futuras",
    "preguntar_cliente_dudas",
    "confirmar_cliente_entendio",
    "validacion_verbal_conformidad",
    "revisar_fisicamente_vehiculo",
    "validar_estado_estetico",
    "confirmar_sistemas_intervenidos",
    "entregar_factura_orden_final",
    "entregar_desglose_trabajos_costos",
    "obtener_firma_conformidad",
}

# Estos sí pueden cerrarse como N/A cuando realmente no aplican.
ENTREGA_OBLIGATORIOS_OK_O_NA = CHECKLIST_ENTREGA_IDS - ENTREGA_OBLIGATORIOS_OK
