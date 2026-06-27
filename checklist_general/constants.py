CHECKLIST_GENERAL = [
    {
        "titulo": "1. VALIDACIÓN ADMINISTRATIVA PREVIA",
        "items": [
            ("pre_factura_preparada", "Pre-factura preparada"),
            ("orden_servicio_final_impresa_firmas", "Orden de servicio final impresa con firmas"),
            ("garantias_documentadas", "Garantías documentadas"),
            ("salida_almacen", "Salida de almacén"),
        ],
    },
    {
        "titulo": "2. VALIDACIÓN TÉCNICA FINAL EN TALLER",
        "items": [
            ("torque_correcto_componentes", "Verificar torque correcto en componentes intervenidos"),
            ("ausencia_fugas", "Validar ausencia de fugas"),
            ("niveles_fluidos_correctos", "Confirmar niveles correctos de fluidos"),
            ("instalacion_piezas_conectores", "Verificar correcta instalación de piezas y conectores"),
            ("escaneo_final_realizado", "Escaneo final realizado"),
            ("sin_codigos_dtc_activos", "Sin códigos DTC activos"),
            ("reinicio_recordatorios_mantenimiento", "Reinicio correcto de recordatorios de mantenimiento"),
            ("apriete_ruedas", "Confirmar apriete de ruedas"),
            ("presion_neumaticos", "Verificar presión de neumáticos"),
            ("funcionamiento_frenos", "Confirmar funcionamiento de frenos"),
            ("funcionamiento_luces", "Verificar funcionamiento de luces"),
            ("limpiaparabrisas_lavaparabrisas", "Verificar limpiaparabrisas y lavaparabrisas"),
            ("funcionamiento_cinturones", "Validar funcionamiento de cinturones"),
        ],
    },
    {
        "titulo": "3. CHECKLIST DE PRUEBA DE MANEJO",
        "items": [
            ("encendido_correcto", "Encendido correcto"),
            ("marcha_minima_estable", "Marcha mínima estable"),
            ("sin_vibraciones_anormales_ruta", "Sin vibraciones anormales"),
            ("aceleracion_normal", "Aceleración normal"),
            ("sin_perdida_potencia", "Sin pérdida de potencia"),
            ("temperatura_operacion_normal", "Temperatura de operación normal"),
            ("sin_ruidos_interiores", "Sin ruidos interiores"),
            ("sin_olores_extranos", "Sin olores extraños"),
            ("cambios_suaves_acople_marchas", "Cambios suaves y acople de marchas"),
            ("sin_jaloneos", "Sin jaloneos"),
            ("sin_ruidos_anormales_transmision", "Sin ruidos anormales en transmisión"),
            ("sin_ruidos_suspension", "Sin ruidos en suspensión"),
            ("alineacion_validada", "Alineación validada"),
            ("frenos_sin_ruidos_rechinidos", "Frenos sin ruidos o rechinidos"),
            ("aire_acondicionado_funcional", "Aire acondicionado funcional"),
            ("audio_pantalla_funcionales", "Audio y pantalla funcionales"),
        ],
    },
    {
        "titulo": "4. INSPECCIÓN ESTÉTICA FINAL",
        "items": [
            ("vehiculo_lavado", "Vehículo lavado"),
            ("sin_manchas_grasa", "Sin manchas de grasa"),
            ("cofre_puertas_cajuela_limpias", "Cofre, puertas y cajuela limpias"),
            ("sin_danos_nuevos", "Sin daños nuevos"),
            ("proteccion_removida_correctamente", "Protección removida correctamente"),
            ("asientos_limpios", "Asientos limpios"),
            ("volante_palanca_limpios", "Volante y palanca limpios"),
            ("tapetes_limpios", "Tapetes limpios"),
            ("sin_residuos_taller", "Sin residuos de taller"),
            ("sin_herramientas_olvidadas", "Sin herramientas olvidadas"),
        ],
    },
    {
        "titulo": "5. VALIDACIÓN FINAL DE CALIDAD (ANDON)",
        "items": [
            ("checklist_completo_firmado", "Checklist completo y firmado"),
            ("prueba_manejo_validada", "Prueba de manejo validada"),
            ("sin_pendientes_tecnicos", "Sin pendientes técnicos"),
            ("vehiculo_listo_entrega", "Vehículo listo para entrega"),
            ("asesor_informado_liberacion", "Asesor informado de liberación"),
        ],
    },
    {
        "titulo": "6. CONFIRMACIÓN PREVIA A ENTREGA CON CLIENTE",
        "items": [
            ("explicar_trabajos_realizados", "Explicar trabajos realizados"),
            ("explicar_pruebas_efectuadas", "Explicar pruebas efectuadas"),
            ("explicar_garantia", "Explicar garantía"),
            ("informar_recomendaciones_futuras", "Informar recomendaciones futuras"),
            ("resolver_dudas_cliente", "Resolver dudas del cliente"),
            ("revisar_unidad_junto_cliente", "Revisar unidad junto al cliente"),
            ("recordatorio_encuesta_satisfaccion", "Recordatorio de encuesta de satisfacción"),
            ("confirmar_refacciones_cliente", "Confirmar con el cliente si requiere llevarse sus refacciones reemplazadas"),
            ("concientizacion_residuo_peligroso", "Si aplica residuo peligroso, firmar concientización de riesgos y explicar sugerencias"),
        ],
    },
]

CHECKLIST_GENERAL_IDS = {
    item_id
    for seccion in CHECKLIST_GENERAL
    for item_id, _descripcion in seccion["items"]
}

CHECKLIST_GENERAL_MAP = {
    item_id: descripcion
    for seccion in CHECKLIST_GENERAL
    for item_id, descripcion in seccion["items"]
}

PRUEBA_MANEJO_IDS = {
    "encendido_correcto",
    "marcha_minima_estable",
    "sin_vibraciones_anormales_ruta",
    "aceleracion_normal",
    "sin_perdida_potencia",
    "temperatura_operacion_normal",
    "sin_ruidos_interiores",
    "sin_olores_extranos",
    "cambios_suaves_acople_marchas",
    "sin_jaloneos",
    "sin_ruidos_anormales_transmision",
    "sin_ruidos_suspension",
    "alineacion_validada",
    "frenos_sin_ruidos_rechinidos",
    "aire_acondicionado_funcional",
    "audio_pantalla_funcionales",
}

# Estos puntos pueden marcarse N/A cuando realmente no aplican.
GENERAL_OK_O_NA = {
    "confirmar_refacciones_cliente",
    "concientizacion_residuo_peligroso",
}

# Todo lo demás se considera liberación de calidad y debe quedar Correcto para terminar.
GENERAL_OBLIGATORIOS_OK = CHECKLIST_GENERAL_IDS - GENERAL_OK_O_NA
