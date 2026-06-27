from django.conf import settings
from openai import OpenAI


PROMPT_RESUMEN = """
Eres un analista comercial experto en conversaciones de WhatsApp dentro de un CRM automotriz.

Tu tarea es leer TODA la conversación y redactar un resumen general, detallado y útil para seguimiento comercial.

Debes identificar, cuando exista en la conversación:
- nombre del prospecto
- vehículo o versión de interés
- año o modelo mencionado
- uso o necesidad del vehículo
- nivel de interés del prospecto
- si pidió cotización
- si pidió crédito, financiamiento, arrendamiento o plan tradicional
- si pidió que lo contacte un asesor
- objeciones, dudas o aclaraciones importantes
- errores o deficiencias en la calidad de respuesta de la IA o del asesor
- si el prospecto dejó de responder
- siguiente paso comercial sugerido
- recomendacion para mejorar la calidad de atencion o si esta bien atendido el cliente

Reglas:
- No inventes datos.
- Si algo no aparece, simplemente no lo menciones.
- El resumen debe estar redactado en español.
- Debe ser un texto corrido, claro, útil, profesional y entendible para un asesor.
- Debe sonar como nota comercial interna de CRM.
- No uses viñetas.
- No regreses JSON.
- No repitas literalmente toda la conversación.
- El resumen general maximo 30 palabras. Adicionalmente agrega un parrafo de status actual del prospecto max 5 palabras, otro parrafo de retroalimentacion max 15 palabras,
  otro parrafo para la deficiencia de la atencion al prospecto, deficiencia de la IA o asesor si es que se involucro max 20 palabras, otro parrafo para definir cual es el
  siguiente paso recomendable a seguir max 15 palabras y uno ultimo para dar una recomendacion extra para continuar con el proceso de prospeccion e incrementar la probabilidad
  de que se lleve a cabo la venta max 30 palabras.
- El formato que debes devolver es:
  Resumen General:
  Status:
  Retroalimentacion:
  Deficiencia:
  Siguiente paso:
  Recomendacion:
"""

def _rol_mensaje(direction: str) -> str:
    return "Prospecto" if direction == "in" else "IA"

def construir_conversacion_para_resumen(mensajes) -> str:
    lineas = []

    for msg in mensajes:
        texto = (msg.body or "").strip()
        if not texto:
            continue

        rol = _rol_mensaje(msg.direction)
        fecha = msg.created_at.strftime("%Y-%m-%d %H:%M:%S") if msg.created_at else ""
        lineas.append(f"[{fecha}] {rol}: {texto}")

    return "\n".join(lineas).strip()

def generar_resumen_con_openai(*, mensajes, telefono: str = "") -> str:
    texto_conversacion = construir_conversacion_para_resumen(mensajes)

    if not texto_conversacion:
        return ""

    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    contenido_usuario = f"""
Teléfono del prospecto: {telefono}

Analiza esta conversación y genera el resumen solicitado:

{texto_conversacion}
""".strip()
    response = client.chat.completions.create(
        model=getattr(settings, "OPENAI_SUMMARY_MODEL", "gpt-5-mini"),
        messages=[
            {"role": "system", "content": PROMPT_RESUMEN},
            {"role": "user", "content": contenido_usuario},
        ],
    )

    resumen = (response.choices[0].message.content or "").strip()
    return resumen