import os
from io import BytesIO
from xml.sax.saxutils import escape

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

from rest_framework import status, viewsets, permissions
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
from rest_framework.response import Response

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
)

from usuarios.authentication import SignedUserAuthentication
from .models import RecepcionVolvo
from .serializers import RecepcionVolvoSerializer


VOLVO_MAIN = colors.HexColor("#212721")
VOLVO_DARK = colors.HexColor("#212721")
VOLVO_GRAY = colors.HexColor("#64748B")
VOLVO_LIGHT = colors.HexColor("#F4F7FA")
VOLVO_BORDER = colors.HexColor("#CBD5E1")
VOLVO_SOFT = colors.HexColor("#EEF2F1")

WHITE = colors.white
BLACK = colors.HexColor("#0F172A")

VOLVO_BLUE = VOLVO_MAIN
VOLVO_BLUE_2 = VOLVO_DARK

CHECKLIST_VOLVO = [
    {
        "titulo": "INSPECCIÓN FÍSICA",
        "items": [
            ("revisar_carroceria", "Revisar carrocería junto con el cliente"),
            ("registrar_danos", "Registrar golpes, rayones o daños existentes"),
            ("tomar_fotografias", "Tomar fotografías del vehículo"),
            ("revisar_llantas_rines", "Revisar estado de llantas y rines"),
            ("verificar_combustible", "Verificar nivel de combustible"),
            ("revisar_testigos_tablero", "Revisar testigos encendidos en tablero si aplica"),
            ("confirmar_funcionamiento_basico", "Confirmar funcionamiento básico exterior, interior y componentes mecánicos"),
        ],
    },
    {
        "titulo": "OBJETOS Y PERTENENCIAS",
        "items": [
            ("registrar_objetos_valor", "Registrar objetos de valor visibles"),
            ("confirmar_herramientas_accesorios", "Confirmar herramientas o accesorios incluidos"),
            ("solicitar_retiro_pertenencias", "Solicitar retiro de pertenencias importantes o registrarlas"),
        ],
    },
    {
        "titulo": "IDENTIFICACIÓN DE NECESIDADES",
        "items": [
            ("documentar_falla", "Escuchar y documentar claramente la falla reportada"),
            ("confirmar_sintomas", "Confirmar síntomas, frecuencia y condiciones de la falla"),
            ("preguntas_diagnostico", "Realizar preguntas de diagnóstico relevantes"),
            ("validar_trabajos_previos", "Validar si existen trabajos previos relacionados"),
            ("prueba_ruta_cliente", "Salir a prueba de ruta con cliente si es necesario"),
        ],
    },
    {
        "titulo": "EXPLICACIÓN INICIAL AL CLIENTE",
        "items": [
            ("explicar_diagnostico", "Explicar el proceso de diagnóstico"),
            ("informar_tiempos", "Informar tiempos estimados"),
            ("informar_costos_revision", "Informar posibles costos de revisión"),
            ("explicar_autorizacion_adicional", "Explicar política de autorización adicional"),
            ("confirmar_sin_trabajo_no_autorizado", "Confirmar que ningún trabajo adicional se realizará sin autorización"),
        ],
    },
    {
        "titulo": "DOCUMENTACIÓN Y AUTORIZACIÓN",
        "items": [
            ("generar_orden_servicio", "Generar orden de servicio"),
            ("obtener_firma_autorizacion", "Obtener firma de autorización del cliente"),
            ("entregar_copia_fisica", "Entregar copia física"),
            ("confirmar_preferencia_contacto", "Confirmar preferencia de contacto WhatsApp/correo"),
        ],
    },
]


def normalizar_rol(request):
    return str(getattr(request.user, "rol", "") or "").strip().lower()


def es_admin(request):
    rol = normalizar_rol(request)
    permisos = getattr(request.user, "permisos", []) or []
    permisos = [str(p).lower() for p in permisos]

    return (
        "administrador" in rol
        or "admin" in rol
        or "all" in permisos
        or "usuarios_admin" in permisos
    )


def fecha_local(valor):
    if not valor:
        return "—"

    try:
        if timezone.is_aware(valor):
            valor = timezone.localtime(valor)

        return valor.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(valor)


def ahora_formateado():
    return fecha_local(timezone.now())


def texto(valor, default="—"):
    valor = "" if valor is None else str(valor).strip()
    return valor or default


def texto_pdf(valor, default="—"):
    return escape(texto(valor, default)).replace("\n", "<br/>")


def parrafo(valor, estilo, default="—"):
    return Paragraph(texto_pdf(valor, default), estilo)


def estado_label(valor):
    mapa = {
        "ok": "Correcto",
        "observacion": "Con observación",
        "na": "N/A",
    }

    return mapa.get(str(valor or "").strip().lower(), "—")


def ruta_logo_volvo():
    rutas_base = []

    media_root = getattr(settings, "MEDIA_ROOT", "")
    base_dir = getattr(settings, "BASE_DIR", "")

    if media_root:
        rutas_base.append(str(media_root))

    if base_dir:
        rutas_base.append(os.path.join(str(base_dir), "media"))

    posibles = []

    for base in rutas_base:
        posibles.extend([
            os.path.join(base, "logo.png"),
            os.path.join(base, "logos", "logo.png"),
        ])

    for ruta in posibles:
        if os.path.exists(ruta):
            return ruta

    return None

def estilos_pdf():
    return {
        "titulo": ParagraphStyle(
            name="Titulo",
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=16,
            textColor=VOLVO_MAIN,
            alignment=TA_RIGHT,
        ),
        "subtitulo": ParagraphStyle(
            name="Subtitulo",
            fontName="Helvetica",
            fontSize=7.5,
            leading=9,
            textColor=VOLVO_GRAY,
            alignment=TA_RIGHT,
        ),
        "mini": ParagraphStyle(
            name="Mini",
            fontName="Helvetica",
            fontSize=6.5,
            leading=7.5,
            textColor=VOLVO_GRAY,
            alignment=TA_RIGHT,
        ),
        "seccion": ParagraphStyle(
            name="Seccion",
            fontName="Helvetica-Bold",
            fontSize=7.2,
            leading=8,
            textColor=WHITE,
            alignment=TA_LEFT,
        ),
        "th": ParagraphStyle(
            name="TableHeader",
            fontName="Helvetica-Bold",
            fontSize=6.5,
            leading=7.2,
            textColor=WHITE,
            alignment=TA_CENTER,
        ),
        "label": ParagraphStyle(
            name="Label",
            fontName="Helvetica-Bold",
            fontSize=6.5,
            leading=7.3,
            textColor=BLACK,
        ),
        "value": ParagraphStyle(
            name="Value",
            fontName="Helvetica",
            fontSize=6.5,
            leading=7.3,
            textColor=BLACK,
        ),
        "item": ParagraphStyle(
            name="Item",
            fontName="Helvetica",
            fontSize=5.8,
            leading=6.5,
            textColor=BLACK,
        ),
        "item_bold": ParagraphStyle(
            name="ItemBold",
            fontName="Helvetica-Bold",
            fontSize=5.8,
            leading=6.5,
            textColor=BLACK,
        ),
        "estado": ParagraphStyle(
            name="Estado",
            fontName="Helvetica-Bold",
            fontSize=5.8,
            leading=6.5,
            textColor=BLACK,
            alignment=TA_CENTER,
        ),
        "firma": ParagraphStyle(
            name="Firma",
            fontName="Helvetica-Bold",
            fontSize=6.2,
            leading=7,
            textColor=BLACK,
            alignment=TA_CENTER,
        ),
    }

def fondo_pdf(canvas, doc):
    ancho, alto = doc.pagesize

    canvas.saveState()

    canvas.setFillColor(WHITE)
    canvas.rect(0, 0, ancho, alto, stroke=0, fill=1)

    canvas.setStrokeColor(VOLVO_MAIN)
    canvas.setLineWidth(0.9)
    canvas.roundRect(
        0.28 * cm,
        0.28 * cm,
        ancho - 0.56 * cm,
        alto - 0.56 * cm,
        7,
        stroke=1,
        fill=0,
    )

    canvas.setFont("Helvetica", 6)
    canvas.setFillColor(VOLVO_GRAY)
    canvas.drawRightString(
        ancho - 0.55 * cm,
        0.33 * cm,
        "Checklist de recepción Volvo",
    )

    canvas.restoreState()

def pdf_response(story, filename):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=0.45 * cm,
        leftMargin=0.45 * cm,
        topMargin=0.45 * cm,
        bottomMargin=0.45 * cm,
    )

    doc.build(story, onFirstPage=fondo_pdf)

    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response

def barra_seccion(titulo, estilos):
    t = Table(
        [[Paragraph(escape(titulo), estilos["seccion"])]],
        colWidths=[19.4 * cm],
    )

    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), VOLVO_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.3, VOLVO_BLUE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    return t


def tabla_datos_generales(recepcion, estilos):
    cliente = recepcion.cliente

    data = [
        [
            Paragraph("Cliente", estilos["label"]),
            Paragraph(texto_pdf(getattr(cliente, "nombre", "")), estilos["value"]),
            Paragraph("Teléfono", estilos["label"]),
            Paragraph(texto_pdf(getattr(cliente, "telefono", "")), estilos["value"]),
            Paragraph("Correo", estilos["label"]),
            Paragraph(texto_pdf(getattr(cliente, "correo", "")), estilos["value"]),
        ],
        [
            Paragraph("Contacto", estilos["label"]),
            Paragraph(texto_pdf(recepcion.get_metodo_contacto_preferido_display()), estilos["value"]),
            Paragraph("Recepción", estilos["label"]),
            Paragraph(texto_pdf(fecha_local(recepcion.fecha_hora_recepcion)), estilos["value"]),
            Paragraph("Asesor", estilos["label"]),
            Paragraph(texto_pdf(recepcion.asesor_servicio), estilos["value"]),
        ],
        [
            Paragraph("Placas", estilos["label"]),
            Paragraph(texto_pdf(recepcion.placas), estilos["value"]),
            Paragraph("VIN", estilos["label"]),
            Paragraph(texto_pdf(recepcion.vin), estilos["value"]),
            Paragraph("Modelo", estilos["label"]),
            Paragraph(texto_pdf(recepcion.modelo), estilos["value"]),
        ],
        [
            Paragraph("Kilometraje", estilos["label"]),
            Paragraph(texto_pdf(recepcion.kilometraje), estilos["value"]),
            Paragraph("Agencia", estilos["label"]),
            Paragraph(texto_pdf(recepcion.agencia), estilos["value"]),
            Paragraph("Estado", estilos["label"]),
            Paragraph(
                texto_pdf("Terminada" if recepcion.recepcion_terminada else "Abierta"),
                estilos["value"],
            ),
        ],
    ]

    t = Table(
        data,
        colWidths=[
            2.0 * cm, 6.0 * cm,
            2.0 * cm, 5.4 * cm,
            2.0 * cm, 9.4 * cm,
        ],
    )

    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.35, VOLVO_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.20, VOLVO_BORDER),

        ("BACKGROUND", (0, 0), (0, -1), VOLVO_SOFT),
        ("BACKGROUND", (2, 0), (2, -1), VOLVO_SOFT),
        ("BACKGROUND", (4, 0), (4, -1), VOLVO_SOFT),

        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    return t

def color_estado(estado):
    estado = str(estado or "").lower()

    if estado == "ok":
        return colors.HexColor("#D1FAE5")

    if estado == "observacion":
        return colors.HexColor("#FEF3C7")

    if estado == "na":
        return colors.HexColor("#E5E7EB")

    return VOLVO_LIGHT

def tabla_checklist_seccion(titulo, items, checklist, estilos, ancho_cm=13.1):
    rows = [
        [
            Paragraph(escape(titulo), estilos["seccion"]),
            "",
            "",
        ],
        [
            Paragraph("Punto de revisión", estilos["th"]),
            Paragraph("Estado", estilos["th"]),
            Paragraph("Comentario", estilos["th"]),
        ],
    ]

    for item_id, descripcion in items:
        valor = checklist.get(item_id, {}) if isinstance(checklist, dict) else {}

        estado = valor.get("estado", "") if isinstance(valor, dict) else ""
        comentario = valor.get("comentario", "") if isinstance(valor, dict) else ""

        rows.append([
            Paragraph(escape(descripcion), estilos["item"]),
            Paragraph(escape(estado_label(estado)), estilos["estado"]),
            Paragraph(texto_pdf(recortar(comentario, 55), ""), estilos["item"]),
        ])

    t = Table(
        rows,
        colWidths=[
            (ancho_cm - 5.3) * cm,
            2.3 * cm,
            3.0 * cm,
        ],
    )

    style = [
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), VOLVO_MAIN),
        ("BACKGROUND", (0, 1), (-1, 1), VOLVO_MAIN),

        ("BOX", (0, 0), (-1, -1), 0.35, VOLVO_BORDER),
        ("INNERGRID", (0, 1), (-1, -1), 0.20, VOLVO_BORDER),

        ("VALIGN", (0, 0), (-1, -1), "TOP"),

        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),

        ("ALIGN", (1, 2), (1, -1), "CENTER"),
    ]

    row_index = 2

    for item_id, _descripcion in items:
        valor = checklist.get(item_id, {}) if isinstance(checklist, dict) else {}
        estado = valor.get("estado", "") if isinstance(valor, dict) else ""

        style.append(("BACKGROUND", (1, row_index), (1, row_index), color_estado(estado)))
        row_index += 1

    t.setStyle(TableStyle(style))

    return t


def columna_checklist(secciones, checklist, estilos):
    flow = []

    for index, seccion in enumerate(secciones):
        if index > 0:
            flow.append(Spacer(1, 3))

        flow.append(
            tabla_checklist_seccion(
                seccion["titulo"],
                seccion["items"],
                checklist,
                estilos,
                ancho_cm=13.1,
            )
        )

    return flow


def bloque_checklist_dos_columnas(recepcion, estilos):
    checklist = recepcion.checklist or {}

    if not isinstance(checklist, dict):
        checklist = {}

    izquierda = CHECKLIST_VOLVO[:2]
    derecha = CHECKLIST_VOLVO[2:]

    left_flow = columna_checklist(izquierda, checklist, estilos)
    right_flow = columna_checklist(derecha, checklist, estilos)

    t = Table(
        [[left_flow, "", right_flow]],
        colWidths=[13.1 * cm, 0.55 * cm, 13.1 * cm],
    )

    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    return t

def header_pdf(recepcion, estilos):
    logo_path = ruta_logo_volvo()
    logo = crear_logo_pdf(logo_path, max_width_cm=4.0, max_height_cm=1.0)

    derecha = [
        Paragraph("CHECKLIST DE RECEPCIÓN DE VEHÍCULO", estilos["titulo"]),
        Paragraph(
            f"Folio: {recepcion.id} &nbsp;&nbsp; Generado: {escape(ahora_formateado())}",
            estilos["mini"],
        ),
    ]

    t = Table(
        [[logo, derecha]],
        colWidths=[7.0 * cm, 19.8 * cm],
    )

    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.9, VOLVO_MAIN),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    return t

def bloque_observaciones_y_firmas(recepcion, estilos):
    obs = Table(
        [
            [
                Paragraph("OBSERVACIONES GENERALES", estilos["th"]),
            ],
            [
                Paragraph(
                    texto_pdf(recortar(recepcion.observaciones, 260), "Sin observaciones."),
                    estilos["value"],
                ),
            ],
        ],
        colWidths=[10.6 * cm],
        rowHeights=[0.38 * cm, 1.02 * cm],
    )

    obs.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), VOLVO_MAIN),
        ("BOX", (0, 0), (-1, -1), 0.35, VOLVO_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    t = Table(
        [[obs, "", firmas(estilos)]],
        colWidths=[10.6 * cm, 0.55 * cm, 15.6 * cm],
    )

    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    return t

def firmas(estilos):
    t = Table(
        [
            ["", "", ""],
            [
                Paragraph("ASESOR DE SERVICIO<br/><font size='5'>Nombre y firma</font>", estilos["firma"]),
                Paragraph("CLIENTE<br/><font size='5'>Nombre y firma</font>", estilos["firma"]),
                Paragraph("TÉCNICO / RECEPCIÓN<br/><font size='5'>Nombre y firma</font>", estilos["firma"]),
            ],
        ],
        colWidths=[5.2 * cm, 5.2 * cm, 5.2 * cm],
        rowHeights=[0.45 * cm, 0.45 * cm],
    )

    t.setStyle(TableStyle([
        ("LINEABOVE", (0, 1), (0, 1), 0.7, BLACK),
        ("LINEABOVE", (1, 1), (1, 1), 0.7, BLACK),
        ("LINEABOVE", (2, 1), (2, 1), 0.7, BLACK),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    return t

def recortar(valor, limite=70, default=""):
    valor = "" if valor is None else str(valor).strip()

    if not valor:
        return default

    if len(valor) <= limite:
        return valor

    return valor[:limite].rstrip() + "..."


def crear_logo_pdf(path, max_width_cm=4.0, max_height_cm=1.0):
    if not path or not os.path.exists(path):
        return Paragraph("", ParagraphStyle(name="LogoVacio"))

    img = Image(path)

    ancho_original = float(img.imageWidth or 1)
    alto_original = float(img.imageHeight or 1)

    max_w = max_width_cm * cm
    max_h = max_height_cm * cm

    factor = min(max_w / ancho_original, max_h / alto_original)

    img.drawWidth = ancho_original * factor
    img.drawHeight = alto_original * factor
    img.hAlign = "LEFT"

    return img

def generar_pdf_recepcion_volvo(recepcion):
    estilos = estilos_pdf()

    story = []

    story.append(header_pdf(recepcion, estilos))
    story.append(Spacer(1, 4))

    story.append(tabla_datos_generales(recepcion, estilos))
    story.append(Spacer(1, 5))

    story.append(bloque_checklist_dos_columnas(recepcion, estilos))
    story.append(Spacer(1, 5))

    story.append(bloque_observaciones_y_firmas(recepcion, estilos))

    return pdf_response(
        story,
        f"checklist_recepcion_volvo_{recepcion.id}.pdf",
    )

class RecepcionVolvoViewSet(viewsets.ModelViewSet):
    authentication_classes = [SignedUserAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    queryset = (
        RecepcionVolvo.objects
        .select_related("cliente")
        .prefetch_related("evidencias")
        .all()
        .order_by("-creado")
    )

    serializer_class = RecepcionVolvoSerializer
    filter_backends = [OrderingFilter, SearchFilter]

    ordering_fields = [
        "creado",
        "actualizado",
        "fecha_hora_recepcion",
        "agencia",
        "asesor_servicio",
        "placas",
        "vin",
        "modelo",
        "kilometraje",
    ]

    search_fields = [
        "agencia",
        "asesor_servicio",
        "placas",
        "vin",
        "modelo",
        "kilometraje",
        "observaciones",
        "cliente__nombre",
        "cliente__telefono",
        "cliente__correo",
    ]

    def get_queryset(self):
        qs = super().get_queryset()

        if es_admin(self.request):
            return qs

        agencia = str(getattr(self.request.user, "agencia", "") or "").strip()

        if agencia:
            qs = qs.filter(agencia=agencia)

        return qs

    def update(self, request, *args, **kwargs):
        instance = self.get_object()

        if instance.recepcion_terminada:
            return Response(
                {"detail": "Esta recepción ya está terminada y no se puede editar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()

        if instance.recepcion_terminada:
            return Response(
                {"detail": "Esta recepción ya está terminada y no se puede editar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().partial_update(request, *args, **kwargs)

    @action(detail=True, methods=["patch"], url_path="terminar")
    def terminar(self, request, pk=None):
        recepcion = self.get_object()

        if recepcion.recepcion_terminada:
            return Response(
                {"detail": "La recepción ya estaba terminada."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        recepcion.recepcion_terminada = True
        recepcion.fecha_terminada = timezone.now()
        recepcion.save(update_fields=[
            "recepcion_terminada",
            "fecha_terminada",
            "actualizado",
        ])

        serializer = self.get_serializer(recepcion)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="checklist-pdf")
    def checklist_pdf(self, request, pk=None):
        recepcion = self.get_object()
        return generar_pdf_recepcion_volvo(recepcion)