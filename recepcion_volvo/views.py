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
from reportlab.lib.pagesizes import letter
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


VOLVO_BLUE = colors.HexColor("#212721")
VOLVO_BLUE_2 = colors.HexColor("#0B2C5F")
VOLVO_GRAY = colors.HexColor("#64748B")
VOLVO_LIGHT = colors.HexColor("#F4F7FA")
VOLVO_BORDER = colors.HexColor("#CBD5E1")
WHITE = colors.white
BLACK = colors.HexColor("#0F172A")

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
            os.path.join(base, "volvo.png"),
            os.path.join(base, "logos", "volvo.png"),
            os.path.join(base, "Volvo.png"),
            os.path.join(base, "logos", "Volvo.png"),
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
            fontSize=17,
            leading=20,
            textColor=VOLVO_BLUE,
            alignment=TA_RIGHT,
        ),
        "subtitulo": ParagraphStyle(
            name="Subtitulo",
            fontName="Helvetica",
            fontSize=9,
            leading=11,
            textColor=VOLVO_GRAY,
            alignment=TA_RIGHT,
        ),
        "seccion": ParagraphStyle(
            name="Seccion",
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=WHITE,
            alignment=TA_LEFT,
        ),
        "label": ParagraphStyle(
            name="Label",
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            textColor=BLACK,
        ),
        "value": ParagraphStyle(
            name="Value",
            fontName="Helvetica",
            fontSize=7.5,
            leading=9,
            textColor=BLACK,
        ),
        "item": ParagraphStyle(
            name="Item",
            fontName="Helvetica",
            fontSize=7.2,
            leading=8.5,
            textColor=BLACK,
        ),
        "estado": ParagraphStyle(
            name="Estado",
            fontName="Helvetica-Bold",
            fontSize=7.2,
            leading=8.5,
            textColor=BLACK,
            alignment=TA_CENTER,
        ),
        "firma": ParagraphStyle(
            name="Firma",
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            textColor=BLACK,
            alignment=TA_CENTER,
        ),
        "mini": ParagraphStyle(
            name="Mini",
            fontName="Helvetica",
            fontSize=7,
            leading=8,
            textColor=VOLVO_GRAY,
            alignment=TA_RIGHT,
        ),
    }


def fondo_pdf(canvas, doc):
    ancho, alto = doc.pagesize

    canvas.saveState()

    canvas.setFillColor(WHITE)
    canvas.rect(0, 0, ancho, alto, stroke=0, fill=1)

    canvas.setStrokeColor(VOLVO_BLUE)
    canvas.setLineWidth(1.1)
    canvas.roundRect(
        0.35 * cm,
        0.35 * cm,
        ancho - 0.70 * cm,
        alto - 0.70 * cm,
        8,
        stroke=1,
        fill=0,
    )

    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(VOLVO_GRAY)
    canvas.drawRightString(ancho - 0.7 * cm, 0.55 * cm, f"Página {canvas.getPageNumber()}")

    canvas.restoreState()


def pdf_response(story, filename):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.8 * cm,
        leftMargin=0.8 * cm,
        topMargin=0.8 * cm,
        bottomMargin=0.9 * cm,
    )

    doc.build(story, onFirstPage=fondo_pdf, onLaterPages=fondo_pdf)

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


def tabla_datos(filas, estilos):
    data = []

    for fila in filas:
        if len(fila) == 4:
            e1, v1, e2, v2 = fila
        elif len(fila) == 2:
            e1, v1 = fila
            e2, v2 = "", ""
        else:
            continue

        data.append([
            parrafo(e1, estilos["label"]),
            parrafo(v1, estilos["value"]),
            parrafo(e2, estilos["label"]),
            parrafo(v2, estilos["value"]),
        ])

    t = Table(
        data,
        colWidths=[3.0 * cm, 6.7 * cm, 3.0 * cm, 6.7 * cm],
    )

    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.45, VOLVO_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, VOLVO_BORDER),
        ("BACKGROUND", (0, 0), (0, -1), VOLVO_LIGHT),
        ("BACKGROUND", (2, 0), (2, -1), VOLVO_LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
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


def tabla_checklist(recepcion, estilos):
    checklist = recepcion.checklist or {}

    rows = [
        [
            Paragraph("Sección", estilos["label"]),
            Paragraph("Punto de revisión", estilos["label"]),
            Paragraph("Estado", estilos["label"]),
            Paragraph("Comentario", estilos["label"]),
        ]
    ]

    section_spans = []
    current_row = 1

    for seccion in CHECKLIST_VOLVO:
        inicio = current_row

        for item_id, descripcion in seccion["items"]:
            valor = checklist.get(item_id, {}) if isinstance(checklist, dict) else {}

            estado = valor.get("estado", "") if isinstance(valor, dict) else ""
            comentario = valor.get("comentario", "") if isinstance(valor, dict) else ""

            rows.append([
                Paragraph(escape(seccion["titulo"]), estilos["item"]),
                Paragraph(escape(descripcion), estilos["item"]),
                Paragraph(escape(estado_label(estado)), estilos["estado"]),
                Paragraph(texto_pdf(comentario, ""), estilos["item"]),
            ])

            current_row += 1

        fin = current_row - 1
        section_spans.append((inicio, fin))

    t = Table(
        rows,
        colWidths=[3.5 * cm, 7.2 * cm, 2.8 * cm, 5.9 * cm],
        repeatRows=1,
    )

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), VOLVO_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.45, VOLVO_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, VOLVO_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]

    row_index = 1

    for seccion in CHECKLIST_VOLVO:
        for item_id, _descripcion in seccion["items"]:
            valor = checklist.get(item_id, {}) if isinstance(checklist, dict) else {}
            estado = valor.get("estado", "") if isinstance(valor, dict) else ""
            style.append(("BACKGROUND", (2, row_index), (2, row_index), color_estado(estado)))
            row_index += 1

    t.setStyle(TableStyle(style))
    return t


def header_pdf(recepcion, estilos):
    logo_path = ruta_logo_volvo()

    if logo_path:
        logo = Image(logo_path)
        logo.drawHeight = 0.9 * cm
        logo.drawWidth = 2.8 * cm
        logo.hAlign = "LEFT"
        izquierda = [logo]
    else:
        izquierda = [
            Paragraph(
                "<b>VOLVO</b>",
                ParagraphStyle(
                    name="LogoTexto",
                    fontName="Helvetica-Bold",
                    fontSize=16,
                    leading=18,
                    textColor=VOLVO_BLUE,
                ),
            )
        ]

    derecha = [
        Paragraph("CHECKLIST DE RECEPCIÓN DE VEHÍCULO", estilos["titulo"]),
        Paragraph("Volvo · Recepción de servicio", estilos["subtitulo"]),
        Spacer(1, 3),
        Paragraph(
            f"Folio: {recepcion.id} &nbsp;&nbsp; Generado: {escape(ahora_formateado())}",
            estilos["mini"],
        ),
    ]

    t = Table(
        [[izquierda, derecha]],
        colWidths=[5.5 * cm, 13.9 * cm],
    )

    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 1.1, VOLVO_BLUE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    return t


def firmas(estilos):
    t = Table(
        [
            ["", "", ""],
            [
                Paragraph("ASESOR DE SERVICIO<br/><font size='6'>Nombre y firma</font>", estilos["firma"]),
                Paragraph("CLIENTE<br/><font size='6'>Nombre y firma</font>", estilos["firma"]),
                Paragraph("TÉCNICO / RECEPCIÓN<br/><font size='6'>Nombre y firma</font>", estilos["firma"]),
            ],
        ],
        colWidths=[6.1 * cm, 6.1 * cm, 6.1 * cm],
        rowHeights=[0.8 * cm, 0.75 * cm],
    )

    t.setStyle(TableStyle([
        ("LINEABOVE", (0, 1), (0, 1), 0.8, BLACK),
        ("LINEABOVE", (1, 1), (1, 1), 0.8, BLACK),
        ("LINEABOVE", (2, 1), (2, 1), 0.8, BLACK),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))

    return t


def generar_pdf_recepcion_volvo(recepcion):
    estilos = estilos_pdf()
    cliente = recepcion.cliente

    story = []

    story.append(header_pdf(recepcion, estilos))
    story.append(Spacer(1, 8))

    story.append(barra_seccion("DATOS DEL CLIENTE", estilos))
    story.append(tabla_datos([
        (
            "Cliente",
            getattr(cliente, "nombre", ""),
            "Teléfono",
            getattr(cliente, "telefono", ""),
        ),
        (
            "Correo",
            getattr(cliente, "correo", ""),
            "Contacto preferido",
            recepcion.get_metodo_contacto_preferido_display(),
        ),
    ], estilos))
    story.append(Spacer(1, 8))

    story.append(barra_seccion("DATOS DEL VEHÍCULO", estilos))
    story.append(tabla_datos([
        (
            "Placas",
            recepcion.placas,
            "VIN",
            recepcion.vin,
        ),
        (
            "Modelo",
            recepcion.modelo,
            "Kilometraje",
            recepcion.kilometraje,
        ),
        (
            "Recepción",
            fecha_local(recepcion.fecha_hora_recepcion),
            "Asesor",
            recepcion.asesor_servicio,
        ),
    ], estilos))
    story.append(Spacer(1, 8))

    story.append(barra_seccion("CHECKLIST DE RECEPCIÓN", estilos))
    story.append(tabla_checklist(recepcion, estilos))
    story.append(Spacer(1, 8))

    story.append(barra_seccion("OBSERVACIONES GENERALES", estilos))

    obs = Table(
        [[Paragraph(texto_pdf(recepcion.observaciones, "Sin observaciones."), estilos["value"])]],
        colWidths=[19.4 * cm],
        rowHeights=[2.0 * cm],
    )

    obs.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.45, VOLVO_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    story.append(obs)
    story.append(Spacer(1, 18))
    story.append(firmas(estilos))

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