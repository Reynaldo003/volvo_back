# Digitales/views.py
from django.http import HttpResponse
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from citas.models import ClienteComercial, normaliza_tel_mx
from .models import ExpedienteDigital
from .serializers import ProspectoSerializer


class ProspectosViewSet(viewsets.ModelViewSet):
    serializer_class = ProspectoSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = (
            ExpedienteDigital.objects
            .select_related("cliente")
            .all()
            .order_by("-actualizado", "-creado")
        )

        search = (self.request.query_params.get("search") or "").strip()
        agencia = (self.request.query_params.get("agencia") or "").strip()
        estado = (self.request.query_params.get("estado") or "").strip()
        asesor_digital = (self.request.query_params.get("asesor_digital") or "").strip()
        asesor_ventas = (self.request.query_params.get("asesor_ventas") or "").strip()

        if search:
            queryset = queryset.filter(
                Q(cliente__nombre__icontains=search)
                | Q(cliente__telefono__icontains=search)
                | Q(cliente__correo__icontains=search)
                | Q(agencia__icontains=search)
                | Q(business__icontains=search)
                | Q(canal_contacto__icontains=search)
                | Q(pauta__icontains=search)
                | Q(estado__icontains=search)
                | Q(auto_interes__icontains=search)
                | Q(asesor_digital__icontains=search)
                | Q(asesor_ventas__icontains=search)
                | Q(comentarios__icontains=search)
            )

        if agencia:
            queryset = queryset.filter(agencia__iexact=agencia)

        if estado:
            queryset = queryset.filter(estado__iexact=estado)

        if asesor_digital:
            queryset = queryset.filter(asesor_digital__icontains=asesor_digital)

        if asesor_ventas:
            queryset = queryset.filter(asesor_ventas__icontains=asesor_ventas)

        return queryset


def bienvenido(request):
    return HttpResponse("Funcionando módulo Digitales Volvo - registro manual de prospectos")


def privacidad_meta_view(request):
    html = """
    <!doctype html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <title>Aviso de Privacidad - CRM Volvo</title>
    </head>
    <body>
        <h1>Aviso de Privacidad</h1>
        <p>
            Automotriz R&R utiliza este sistema CRM Volvo para gestionar
            prospectos y clientes registrados manualmente por el equipo comercial.
        </p>
        <p>
            Los datos personales que pueden tratarse incluyen nombre, teléfono,
            correo electrónico, interés vehicular, agencia de atención,
            asesor asignado y comentarios necesarios para dar seguimiento comercial.
        </p>
        <p>
            La información se utiliza únicamente para brindar atención,
            seguimiento, cotizaciones, programación de citas y mejora del servicio.
        </p>
    </body>
    </html>
    """

    return HttpResponse(html, content_type="text/html; charset=utf-8")


def eliminacion_datos_meta_view(request):
    html = """
    <!doctype html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <title>Eliminación de Datos - CRM Volvo</title>
    </head>
    <body>
        <h1>Instrucciones para eliminación de datos</h1>
        <p>
            Para solicitar la eliminación de tus datos personales almacenados
            en el CRM, contacta al área responsable de Automotriz R&R.
        </p>
        <p>
            Incluye tu nombre completo y número telefónico asociado al registro
            para poder localizar tu información.
        </p>
    </body>
    </html>
    """

    return HttpResponse(html, content_type="text/html; charset=utf-8")


@api_view(["GET"])
@permission_classes([AllowAny])
def chats_list(request):
    return Response([], status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([AllowAny])
def contacto_por_telefono(request):
    telefono = normaliza_tel_mx(request.query_params.get("tel", ""))

    if not telefono:
        return Response(
            {
                "ok": False,
                "error": "Falta tel o el teléfono es inválido.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    cliente = ClienteComercial.objects.filter(telefono=telefono).first()

    if not cliente:
        return Response(
            {
                "ok": True,
                "prospecto": None,
                "mensajes": [],
            },
            status=status.HTTP_200_OK,
        )

    expediente = ExpedienteDigital.objects.filter(cliente=cliente).first()

    return Response(
        {
            "ok": True,
            "prospecto": ProspectoSerializer(expediente).data if expediente else None,
            "mensajes": [],
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def contacto_updates(request):
    return Response(
        {
            "ok": True,
            "mensajes": [],
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def mark_read_view(request):
    return Response({"ok": True}, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([AllowAny])
def enviar_mensaje_view(request):
    return Response(
        {
            "ok": False,
            "error": "WhatsApp está desactivado temporalmente en CRM Volvo.",
        },
        status=status.HTTP_501_NOT_IMPLEMENTED,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def enviar_media_view(request):
    return Response(
        {
            "ok": False,
            "error": "Envío de archivos por WhatsApp desactivado temporalmente en CRM Volvo.",
        },
        status=status.HTTP_501_NOT_IMPLEMENTED,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def enviar_plantilla_view(request):
    return Response(
        {
            "ok": False,
            "error": "Envío de plantillas de WhatsApp desactivado temporalmente en CRM Volvo.",
        },
        status=status.HTTP_501_NOT_IMPLEMENTED,
    )


@api_view(["PATCH"])
@permission_classes([AllowAny])
def editar_mensaje_view(request):
    return Response(
        {
            "ok": False,
            "error": "Edición de mensajes de WhatsApp desactivada temporalmente en CRM Volvo.",
        },
        status=status.HTTP_501_NOT_IMPLEMENTED,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def plantillas_whatsapp_view(request):
    return Response(
        {
            "ok": True,
            "items": [],
            "mensaje": "WhatsApp está desactivado temporalmente en CRM Volvo.",
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def campanas_meta_recientes(request):
    return Response(
        {
            "ok": True,
            "items": [],
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def media_proxy_view(request, media_id):
    return Response(
        {
            "ok": False,
            "error": "Media proxy de WhatsApp desactivado temporalmente en CRM Volvo.",
        },
        status=status.HTTP_501_NOT_IMPLEMENTED,
    )


@csrf_exempt
def webhook(request):
    if request.method == "GET":
        challenge = request.GET.get("hub.challenge", "")

        if challenge:
            return HttpResponse(challenge, content_type="text/plain")

        return HttpResponse("Webhook Volvo desactivado temporalmente.")

    return HttpResponse("ok")