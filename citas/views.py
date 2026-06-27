# citas/views.py
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser

from .models import (
    ClienteComercial,
    Cita,
    RegistroPiso,
    PruebaManejo,
    EvidenciaPruebaManejo,
    Entregas,
)
from .serializers import (
    ClienteComercialSerializer,
    CitaSerializer,
    RegistroPisoSerializer,
    PruebaManejoSerializer,
    EvidenciaPruebaManejoSerializer,
    EntregasSerializer,
)


class ClienteComercialViewSet(ModelViewSet):
    queryset = ClienteComercial.objects.all().order_by("-id_cliente")
    serializer_class = ClienteComercialSerializer

    @action(detail=True, methods=["get"])
    def agenda(self, request, pk=None):
        """
        Regresa TODO lo del cliente:
        - citas
        - registro piso
        - pruebas manejo
        - entregas

        Unificado y ordenado por fecha.
        """
        cliente = self.get_object()

        citas = Cita.objects.filter(cliente=cliente).order_by("fecha_hora_cita", "id")
        piso = RegistroPiso.objects.filter(cliente=cliente).order_by("fecha_hora_cita", "id")
        pruebas = PruebaManejo.objects.filter(cliente=cliente).order_by("fecha_hora_cita", "id")
        entregas = Entregas.objects.filter(cliente=cliente).order_by("fecha_hora_entrega", "id")

        data = []

        for x in citas:
            data.append(
                {
                    "tipo": "CITA",
                    "id": x.id,
                    "fecha_hora": x.fecha_hora_cita,
                    "agencia": x.agencia,
                    "auto_interes": x.auto_interes,
                    "asistencia": x.asistencia,
                    "detalle": CitaSerializer(x, context={"request": request}).data,
                }
            )

        for x in piso:
            data.append(
                {
                    "tipo": "REGISTRO_PISO",
                    "id": x.id,
                    "fecha_hora": x.fecha_hora_cita,
                    "agencia": x.agencia,
                    "auto_interes": x.auto_interes,
                    "asistencia": x.asistencia,
                    "detalle": RegistroPisoSerializer(x, context={"request": request}).data,
                }
            )

        for x in pruebas:
            data.append(
                {
                    "tipo": "PRUEBA_MANEJO",
                    "id": x.id,
                    "fecha_hora": x.fecha_hora_cita,
                    "agencia": x.agencia,
                    "auto_interes": x.auto_interes,
                    "asistencia": x.asistencia,
                    "detalle": PruebaManejoSerializer(x, context={"request": request}).data,
                }
            )

        for x in entregas:
            data.append(
                {
                    "tipo": "ENTREGA",
                    "id": x.id,
                    "fecha_hora": x.fecha_hora_entrega,
                    "agencia": x.agencia,
                    "modelo_version": x.modelo_version,
                    "entrega_reportada": x.entrega_reportada,
                    "detalle": EntregasSerializer(x, context={"request": request}).data,
                }
            )

        data.sort(key=lambda r: (r["fecha_hora"] is None, r["fecha_hora"], r["id"]))
        return Response(data)


class CitasViewSet(ModelViewSet):
    queryset = Cita.objects.select_related("cliente").all().order_by("-id")
    serializer_class = CitaSerializer


class RegistroPisoViewSet(ModelViewSet):
    queryset = RegistroPiso.objects.select_related("cliente").all().order_by("-id")
    serializer_class = RegistroPisoSerializer


class PruebasManejoViewSet(ModelViewSet):
    queryset = (
        PruebaManejo.objects.select_related("cliente")
        .prefetch_related("evidencias")
        .all()
        .order_by("-id")
    )
    serializer_class = PruebaManejoSerializer


class EvidenciasPruebaManejoViewSet(ModelViewSet):
    queryset = (
        EvidenciaPruebaManejo.objects.select_related(
            "prueba_manejo",
            "prueba_manejo__cliente",
        )
        .all()
        .order_by("-id")
    )
    serializer_class = EvidenciaPruebaManejoSerializer
    parser_classes = [MultiPartParser, FormParser]


class EntregasViewSet(ModelViewSet):
    queryset = Entregas.objects.select_related("cliente").all().order_by("-id")
    serializer_class = EntregasSerializer