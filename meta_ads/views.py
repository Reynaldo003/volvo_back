# meta_ads/views.py
from datetime import date

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce, ExtractMonth, ExtractYear
from django.utils.dateparse import parse_date

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import CampanaMetaVolvo
from .serializers import CampanaMetaListSerializer, CampanaMetaSerializer


LIST_FIELDS = (
    "id_campana",
    "id_concesionaria",
    "sucursal",
    "inicio_informe",
    "fin_informe",
    "nombre_campana",
    "estado_campana",
    "objetivo_campana",
    "inicio_campana",
    "fin_campana",
    "total_resultados",
    "alcance",
    "impresiones",
    "presupuesto_anuncio",
    "coste_resultados",
    "importe_gastado",
    "total_messaging_connection",
)


class CampanaMetaPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


def valor_vacio(valor):
    valor = (valor or "").strip()
    return valor.lower() in {"", "todos", "todas", "null", "undefined"}


def rango_fecha(anio, mes=None):
    """
    Devuelve un rango [desde, hasta) para filtrar usando índices de fecha.
    Esto es mejor que hacer filtros tipo YEAR(campo) porque SQL Server puede
    aprovechar mejor un índice sobre la columna de fecha.
    """
    if valor_vacio(anio):
        return None, None

    try:
        anio = int(anio)
    except (TypeError, ValueError):
        return None, None

    if valor_vacio(mes):
        return date(anio, 1, 1), date(anio + 1, 1, 1)

    try:
        mes = int(mes)
    except (TypeError, ValueError):
        return date(anio, 1, 1), date(anio + 1, 1, 1)

    if mes < 1 or mes > 12:
        return date(anio, 1, 1), date(anio + 1, 1, 1)

    desde = date(anio, mes, 1)

    if mes == 12:
        hasta = date(anio + 1, 1, 1)
    else:
        hasta = date(anio, mes + 1, 1)

    return desde, hasta


class CampanaMetaViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CampanaMetaSerializer
    permission_classes = [AllowAny]
    pagination_class = CampanaMetaPagination
    lookup_field = "id_campana"

    def get_serializer_class(self):
        if self.action in {"list", "ligero"}:
            return CampanaMetaListSerializer

        return CampanaMetaSerializer

    def get_queryset(self):
        params = self.request.query_params

        qs = CampanaMetaVolvo.objects.using("sqlserver_meta").all()

        q = (params.get("q") or "").strip()
        sucursal = (params.get("sucursal") or "").strip()
        estado_campana = (params.get("estado_campana") or "").strip()
        id_concesionaria = (params.get("id_concesionaria") or "").strip()

        anio = (
            params.get("anio")
            or params.get("año")
            or params.get("year")
            or ""
        )
        mes = params.get("mes") or params.get("month") or ""

        fecha_desde = parse_date(params.get("fecha_desde") or "")
        fecha_hasta = parse_date(params.get("fecha_hasta") or "")

        inicio_campana_desde = parse_date(params.get("inicio_campana_desde") or "")
        inicio_campana_hasta = parse_date(params.get("inicio_campana_hasta") or "")

        if q:
            qs = qs.filter(
                Q(nombre_campana__icontains=q)
                | Q(sucursal__icontains=q)
                | Q(estado_campana__icontains=q)
                | Q(indicador_resultados__icontains=q)
                | Q(objetivo_campana__icontains=q)
            )

        if not valor_vacio(sucursal):
            # Antes usabas icontains. Para botones/selects conviene exacto:
            # es más rápido y evita traer sucursales parecidas por accidente.
            qs = qs.filter(sucursal=sucursal)

        if not valor_vacio(estado_campana):
            qs = qs.filter(estado_campana=estado_campana)

        if id_concesionaria.isdigit():
            qs = qs.filter(id_concesionaria=int(id_concesionaria))

        desde, hasta = rango_fecha(anio, mes)

        if desde and hasta:
            qs = qs.filter(
                Q(inicio_campana__gte=desde, inicio_campana__lt=hasta)
                | Q(
                    inicio_campana__isnull=True,
                    inicio_informe__gte=desde,
                    inicio_informe__lt=hasta,
                )
            )

        if fecha_desde:
            qs = qs.filter(inicio_informe__gte=fecha_desde)

        if fecha_hasta:
            qs = qs.filter(fin_informe__lte=fecha_hasta)

        if inicio_campana_desde:
            qs = qs.filter(inicio_campana__gte=inicio_campana_desde)

        if inicio_campana_hasta:
            qs = qs.filter(inicio_campana__lte=inicio_campana_hasta)

        ordering = params.get("ordering") or "-inicio_informe"

        ordering_permitido = {
            "id_campana",
            "id_concesionaria",
            "sucursal",
            "inicio_informe",
            "fin_informe",
            "nombre_campana",
            "estado_campana",
            "inicio_campana",
            "fin_campana",
            "total_resultados",
            "alcance",
            "impresiones",
            "presupuesto_anuncio",
            "coste_resultados",
            "importe_gastado",
            "-id_campana",
            "-id_concesionaria",
            "-sucursal",
            "-inicio_informe",
            "-fin_informe",
            "-nombre_campana",
            "-estado_campana",
            "-inicio_campana",
            "-fin_campana",
            "-total_resultados",
            "-alcance",
            "-impresiones",
            "-presupuesto_anuncio",
            "-coste_resultados",
            "-importe_gastado",
            "-total_messaging_connection"
        }

        if ordering in ordering_permitido:
            qs = qs.order_by(ordering, "-id_campana")

        if self.action in {"list", "ligero"}:
            qs = qs.only(*LIST_FIELDS)

        return qs

    @action(detail=False, methods=["get"], url_path="ligero")
    def ligero(self, request):
        """
        Endpoint optimizado para el dashboard.

        Antes el front consultaba página por página hasta traer toda la tabla.
        Ahora este endpoint devuelve, en una sola llamada, solo las columnas
        necesarias y ya filtradas desde SQL Server.
        """
        qs = self.get_queryset()
        serializer = CampanaMetaListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="resumen")
    def resumen(self, request):
        qs = self.get_queryset()

        data = qs.aggregate(
            total_campanas=Count("id_campana"),
            total_resultados=Sum("total_resultados"),
            total_messaging_connection=Sum("total_messaging_connection"),
            resultados_fb=Sum("resultados_fb"),
            resultados_ig=Sum("resultados_ig"),
            resultados_wp=Sum("resultados_wp"),
            alcance=Sum("alcance"),
            alcance_fb=Sum("alcance_fb"),
            alcance_ig=Sum("alcance_ig"),
            alcance_wsp=Sum("alcance_wsp"),
            impresiones=Sum("impresiones"),
            impresiones_fb=Sum("impresiones_fb"),
            impresiones_ig=Sum("impresiones_ig"),
            impresiones_wsp=Sum("impresiones_wsp"),
            presupuesto_anuncio=Sum("presupuesto_anuncio"),
            coste_resultados=Sum("coste_resultados"),
            importe_gastado=Sum("importe_gastado"),
            importe_gastado_fb=Sum("importe_gastado_fb"),
            importe_gastado_ig=Sum("importe_gastado_ig"),
            importe_gastado_wsp=Sum("importe_gastado_wsp"),
            lead=Sum("lead"),
            link_click=Sum("link_click"),
            likes=Sum("likes"),
            comment=Sum("comment"),
            post_engagement=Sum("post_engagement"),
            page_engagement=Sum("page_engagement"),
            video_view=Sum("video_view"),
        )

        for key, value in data.items():
            if value is None:
                data[key] = 0

        return Response(data)

    @action(detail=False, methods=["get"], url_path="opciones")
    def opciones(self, request):
        qs = CampanaMetaVolvo.objects.using("sqlserver_meta").all()

        sucursales = (
            qs.exclude(sucursal__isnull=True)
            .exclude(sucursal="")
            .values_list("sucursal", flat=True)
            .distinct()
            .order_by("sucursal")
        )

        estados = (
            qs.exclude(estado_campana__isnull=True)
            .exclude(estado_campana="")
            .values_list("estado_campana", flat=True)
            .distinct()
            .order_by("estado_campana")
        )

        concesionarias = (
            qs.exclude(id_concesionaria__isnull=True)
            .values_list("id_concesionaria", flat=True)
            .distinct()
            .order_by("id_concesionaria")
        )

        fechas = (
            qs.annotate(fecha_base=Coalesce("inicio_campana", "inicio_informe"))
            .exclude(fecha_base__isnull=True)
            .annotate(
                anio=ExtractYear("fecha_base"),
                mes=ExtractMonth("fecha_base"),
            )
            .values("anio", "mes")
            .distinct()
            .order_by("-anio", "mes")
        )

        anio_mes = [
            {
                "anio": item["anio"],
                "mes": item["mes"],
            }
            for item in fechas
            if item["anio"] and item["mes"]
        ]

        anios = sorted(
            {item["anio"] for item in anio_mes if item["anio"]},
            reverse=True,
        )

        meses_por_anio = {}

        for item in anio_mes:
            anio_item = str(item["anio"])
            meses_por_anio.setdefault(anio_item, [])

            if item["mes"] not in meses_por_anio[anio_item]:
                meses_por_anio[anio_item].append(item["mes"])

        for anio_item in meses_por_anio:
            meses_por_anio[anio_item].sort()

        return Response(
            {
                "sucursales": list(sucursales),
                "estados_campana": list(estados),
                "concesionarias": list(concesionarias),
                "anios": anios,
                "anio_mes": anio_mes,
                "meses_por_anio": meses_por_anio,
            }
        )