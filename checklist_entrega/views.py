#checklist_entrega/views.py
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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

from usuarios.authentication import SignedUserAuthentication
from .constants import (
    CHECKLIST_ENTREGA,
    CHECKLIST_ENTREGA_MAP,
    ENTREGA_OBLIGATORIOS_OK,
    ENTREGA_OBLIGATORIOS_OK_O_NA,
)
from .models import ChecklistEntregaVehiculo
from .serializers import ChecklistEntregaVehiculoSerializer


VOLVO_MAIN = colors.HexColor("#212721")
VOLVO_GRAY = colors.HexColor("#64748B")
VOLVO_LIGHT = colors.HexColor("#F4F7FA")
VOLVO_BORDER = colors.HexColor("#CBD5E1")
VOLVO_SOFT = colors.HexColor("#EEF2F1")
WHITE = colors.white
BLACK = colors.HexColor("#0F172A")


def normalizar_rol(request):
    return str(getattr(request.user, "rol", "") or "").strip().lower()


def es_admin(request):
    rol = normalizar_rol(request)
    permisos = getattr(request.user, "permisos", []) or []
    permisos = [str(p).lower() for p in permisos]
    return "administrador" in rol or "admin" in rol or "all" in permisos or "usuarios_admin" in permisos


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


def recortar(valor, limite=90, default=""):
    valor = "" if valor is None else str(valor).strip()
    if not valor:
        return default
    if len(valor) <= limite:
        return valor
    return valor[:limite].rstrip() + "..."


def estado_label(valor):
    mapa = {"ok": "Correcto", "observacion": "Observación", "na": "N/A"}
    return mapa.get(str(valor or "").strip().lower(), "—")


def color_estado(estado):
    estado = str(estado or "").strip().lower()
    if estado == "ok":
        return colors.HexColor("#D1FAE5")
    if estado == "observacion":
        return colors.HexColor("#FEF3C7")
    if estado == "na":
        return colors.HexColor("#E5E7EB")
    return VOLVO_LIGHT


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
        posibles.extend([os.path.join(base, "logo.png"), os.path.join(base, "logos", "logo.png")])

    for ruta in posibles:
        if os.path.exists(ruta):
            return ruta
    return None


def crear_logo_pdf(path, max_width_cm=3.8, max_height_cm=1.05):
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


def estilos_pdf():
    return {
        "titulo": ParagraphStyle(name="Titulo", fontName="Helvetica-Bold", fontSize=14, leading=15.5, textColor=VOLVO_MAIN, alignment=TA_RIGHT),
        "mini": ParagraphStyle(name="Mini", fontName="Helvetica", fontSize=7, leading=8, textColor=VOLVO_GRAY, alignment=TA_RIGHT),
        "seccion": ParagraphStyle(name="Seccion", fontName="Helvetica-Bold", fontSize=7.2, leading=8.2, textColor=WHITE, alignment=TA_LEFT),
        "th": ParagraphStyle(name="TableHeader", fontName="Helvetica-Bold", fontSize=6.6, leading=7.3, textColor=WHITE, alignment=TA_CENTER),
        "label": ParagraphStyle(name="Label", fontName="Helvetica-Bold", fontSize=6.4, leading=7.2, textColor=BLACK),
        "value": ParagraphStyle(name="Value", fontName="Helvetica", fontSize=6.4, leading=7.2, textColor=BLACK),
        "item": ParagraphStyle(name="Item", fontName="Helvetica", fontSize=6.25, leading=7.05, textColor=BLACK),
        "estado": ParagraphStyle(name="Estado", fontName="Helvetica-Bold", fontSize=6.1, leading=6.9, textColor=BLACK, alignment=TA_CENTER),
        "firma": ParagraphStyle(name="Firma", fontName="Helvetica-Bold", fontSize=6.1, leading=7, textColor=BLACK, alignment=TA_CENTER),
        "nota": ParagraphStyle(name="Nota", fontName="Helvetica-Bold", fontSize=6.6, leading=7.6, textColor=VOLVO_MAIN, alignment=TA_LEFT),
    }


def fondo_pdf(canvas, doc):
    ancho, alto = doc.pagesize
    canvas.saveState()
    canvas.setFillColor(WHITE)
    canvas.rect(0, 0, ancho, alto, stroke=0, fill=1)
    canvas.setStrokeColor(VOLVO_MAIN)
    canvas.setLineWidth(0.8)
    canvas.roundRect(0.28 * cm, 0.28 * cm, ancho - 0.56 * cm, alto - 0.56 * cm, 7, stroke=1, fill=0)
    canvas.setFont("Helvetica", 6)
    canvas.setFillColor(VOLVO_GRAY)
    canvas.drawRightString(ancho - 0.55 * cm, 0.35 * cm, "Checklist de entrega de vehículo Volvo")
    canvas.restoreState()


def pdf_response(story, filename):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.50 * cm,
        leftMargin=0.50 * cm,
        topMargin=0.50 * cm,
        bottomMargin=0.65 * cm,
    )
    doc.build(story, onFirstPage=fondo_pdf, onLaterPages=fondo_pdf)
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def header_pdf(entrega, estilos):
    logo = crear_logo_pdf(ruta_logo_volvo(), max_width_cm=3.8, max_height_cm=1.0)
    derecha = [
        Paragraph("CHECKLIST DE ENTREGA DE VEHÍCULO", estilos["titulo"]),
        Paragraph(f"Folio: {entrega.id} &nbsp;&nbsp; Generado: {escape(ahora_formateado())}", estilos["mini"]),
    ]
    t = Table([[logo, derecha]], colWidths=[4.4 * cm, 15.2 * cm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.8, VOLVO_MAIN),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def tabla_datos_generales(entrega, estilos):
    cliente = entrega.cliente
    data = [
        [
            Paragraph("Cliente", estilos["label"]),
            Paragraph(texto_pdf(recortar(getattr(cliente, "nombre", ""), 38)), estilos["value"]),
            Paragraph("Teléfono", estilos["label"]),
            Paragraph(texto_pdf(getattr(cliente, "telefono", "")), estilos["value"]),
            Paragraph("Correo", estilos["label"]),
            Paragraph(texto_pdf(recortar(getattr(cliente, "correo", ""), 34)), estilos["value"]),
        ],
        [
            Paragraph("Entrega", estilos["label"]),
            Paragraph(texto_pdf(fecha_local(entrega.fecha_hora_entrega)), estilos["value"]),
            Paragraph("Asesor", estilos["label"]),
            Paragraph(texto_pdf(recortar(entrega.asesor_servicio, 34)), estilos["value"]),
            Paragraph("Técnico", estilos["label"]),
            Paragraph(texto_pdf(recortar(entrega.tecnico_responsable, 34)), estilos["value"]),
        ],
        [
            Paragraph("Placas", estilos["label"]),
            Paragraph(texto_pdf(entrega.placas), estilos["value"]),
            Paragraph("VIN", estilos["label"]),
            Paragraph(texto_pdf(recortar(entrega.vin, 28)), estilos["value"]),
            Paragraph("Modelo", estilos["label"]),
            Paragraph(texto_pdf(recortar(entrega.modelo, 30)), estilos["value"]),
        ],
        [
            Paragraph("Kilometraje", estilos["label"]),
            Paragraph(texto_pdf(entrega.kilometraje), estilos["value"]),
            Paragraph("Orden", estilos["label"]),
            Paragraph(texto_pdf(entrega.orden_servicio), estilos["value"]),
            Paragraph("Factura", estilos["label"]),
            Paragraph(texto_pdf(entrega.factura), estilos["value"]),
        ],
        [
            Paragraph("Agencia", estilos["label"]),
            Paragraph(texto_pdf(recortar(entrega.agencia, 24)), estilos["value"]),
            Paragraph("Contacto", estilos["label"]),
            Paragraph(texto_pdf(entrega.get_metodo_contacto_preferido_display()), estilos["value"]),
            Paragraph("Estado", estilos["label"]),
            Paragraph(texto_pdf("Terminada" if entrega.entrega_terminada else "Abierta"), estilos["value"]),
        ],
    ]
    t = Table(data, colWidths=[1.8 * cm, 4.9 * cm, 1.8 * cm, 4.0 * cm, 1.8 * cm, 5.3 * cm])
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


def tabla_checklist(entrega, estilos):
    checklist = entrega.checklist or {}
    if not isinstance(checklist, dict):
        checklist = {}

    rows = []
    for seccion in CHECKLIST_ENTREGA:
        rows.append([Paragraph(escape(seccion["titulo"]), estilos["seccion"]), "", ""])
        rows.append([Paragraph("Punto de revisión", estilos["th"]), Paragraph("Estado", estilos["th"]), Paragraph("Comentario", estilos["th"])])
        for item_id, descripcion in seccion["items"]:
            valor = checklist.get(item_id, {}) if isinstance(checklist, dict) else {}
            estado = valor.get("estado", "") if isinstance(valor, dict) else ""
            comentario = valor.get("comentario", "") if isinstance(valor, dict) else ""
            rows.append([
                Paragraph(escape(descripcion), estilos["item"]),
                Paragraph(escape(estado_label(estado)), estilos["estado"]),
                Paragraph(texto_pdf(recortar(comentario, 130), ""), estilos["item"]),
            ])

    t = Table(rows, colWidths=[11.8 * cm, 2.4 * cm, 5.4 * cm], repeatRows=0)
    style = [
        ("BOX", (0, 0), (-1, -1), 0.35, VOLVO_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.18, VOLVO_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
    ]

    row_index = 0
    for seccion in CHECKLIST_ENTREGA:
        style.extend([
            ("SPAN", (0, row_index), (-1, row_index)),
            ("BACKGROUND", (0, row_index), (-1, row_index), VOLVO_MAIN),
        ])
        row_index += 1
        style.append(("BACKGROUND", (0, row_index), (-1, row_index), VOLVO_MAIN))
        row_index += 1
        for item_id, _descripcion in seccion["items"]:
            valor = checklist.get(item_id, {}) if isinstance(checklist, dict) else {}
            estado = valor.get("estado", "") if isinstance(valor, dict) else ""
            style.append(("BACKGROUND", (1, row_index), (1, row_index), color_estado(estado)))
            row_index += 1

    t.setStyle(TableStyle(style))
    return t


def bloque_observaciones(entrega, estilos):
    t = Table(
        [
            [Paragraph("OBSERVACIONES GENERALES", estilos["th"])],
            [Paragraph(texto_pdf(recortar(entrega.observaciones, 700), "Sin observaciones."), estilos["value"])],
        ],
        colWidths=[19.6 * cm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), VOLVO_MAIN),
        ("BOX", (0, 0), (-1, -1), 0.35, VOLVO_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def firmas(estilos):
    t = Table(
        [
            ["", "", ""],
            [
                Paragraph("ASESOR DE SERVICIO<br/><font size='5'>Nombre y firma</font>", estilos["firma"]),
                Paragraph("CLIENTE<br/><font size='5'>Nombre y firma de conformidad</font>", estilos["firma"]),
                Paragraph("TÉCNICO RESPONSABLE<br/><font size='5'>Nombre y firma</font>", estilos["firma"]),
            ],
        ],
        colWidths=[6.25 * cm, 6.25 * cm, 6.25 * cm],
        rowHeights=[0.70 * cm, 0.60 * cm],
    )
    t.setStyle(TableStyle([
        ("LINEABOVE", (0, 1), (0, 1), 0.70, BLACK),
        ("LINEABOVE", (1, 1), (1, 1), 0.70, BLACK),
        ("LINEABOVE", (2, 1), (2, 1), 0.70, BLACK),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, 1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def generar_pdf_checklist_entrega(entrega):
    estilos = estilos_pdf()
    story = [
        header_pdf(entrega, estilos),
        Spacer(1, 5),
        Spacer(1, 5),
        tabla_datos_generales(entrega, estilos),
        Spacer(1, 6),
        tabla_checklist(entrega, estilos),
        Spacer(1, 7),
        bloque_observaciones(entrega, estilos),
        Spacer(1, 12),
        firmas(estilos),
    ]
    return pdf_response(story, f"checklist_entrega_vehiculo_{entrega.id}.pdf")


def validar_entrega_para_cierre(entrega):
    checklist = entrega.checklist or {}
    if not isinstance(checklist, dict):
        checklist = {}

    pendientes = []

    for item_id in sorted(ENTREGA_OBLIGATORIOS_OK):
        estado = str((checklist.get(item_id) or {}).get("estado") or "").strip().lower()
        if estado != "ok":
            pendientes.append(CHECKLIST_ENTREGA_MAP.get(item_id, item_id))

    for item_id in sorted(ENTREGA_OBLIGATORIOS_OK_O_NA):
        estado = str((checklist.get(item_id) or {}).get("estado") or "").strip().lower()
        if estado not in {"ok", "na"}:
            pendientes.append(CHECKLIST_ENTREGA_MAP.get(item_id, item_id))

    return pendientes


class ChecklistEntregaVehiculoViewSet(viewsets.ModelViewSet):
    authentication_classes = [SignedUserAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    queryset = (
        ChecklistEntregaVehiculo.objects
        .select_related("cliente")
        .prefetch_related("evidencias")
        .all()
        .order_by("-creado")
    )
    serializer_class = ChecklistEntregaVehiculoSerializer
    filter_backends = [OrderingFilter, SearchFilter]

    ordering_fields = [
        "creado", "actualizado", "fecha_hora_entrega", "agencia", "asesor_servicio",
        "tecnico_responsable", "placas", "vin", "modelo", "kilometraje", "orden_servicio", "factura",
    ]
    search_fields = [
        "agencia", "asesor_servicio", "tecnico_responsable", "placas", "vin", "modelo",
        "kilometraje", "orden_servicio", "factura", "observaciones", "cliente__nombre",
        "cliente__telefono", "cliente__correo",
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
        if instance.entrega_terminada:
            return Response({"detail": "Esta entrega ya está terminada y no se puede editar."}, status=status.HTTP_400_BAD_REQUEST)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.entrega_terminada:
            return Response({"detail": "Esta entrega ya está terminada y no se puede editar."}, status=status.HTTP_400_BAD_REQUEST)
        return super().partial_update(request, *args, **kwargs)

    @action(detail=True, methods=["patch"], url_path="terminar")
    def terminar(self, request, pk=None):
        entrega = self.get_object()

        if entrega.entrega_terminada:
            return Response({"detail": "La entrega ya estaba terminada."}, status=status.HTTP_400_BAD_REQUEST)

        pendientes = validar_entrega_para_cierre(entrega)
        if pendientes:
            return Response(
                {
                    "detail": "No se puede terminar la entrega. Faltan puntos obligatorios o hay puntos no aplicables sin marcar.",
                    "pendientes": pendientes,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        entrega.entrega_terminada = True
        entrega.fecha_terminada = timezone.now()
        entrega.save(update_fields=["entrega_terminada", "fecha_terminada", "actualizado"])

        serializer = self.get_serializer(entrega)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="checklist-pdf")
    def checklist_pdf(self, request, pk=None):
        entrega = self.get_object()
        return generar_pdf_checklist_entrega(entrega)
