# salesforce/views.py
import logging
from datetime import date, timedelta

from django.db import DatabaseError, connections
from rest_framework import viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param

from .serializers import (
    FiltrosConsultaSerializer,
    OportunidadSerializer,
    ProspectoSerializer,
    TareaSerializer,
)

logger = logging.getLogger(__name__)


def valor_vacio(valor):
    """Permite que el front envíe valores vacíos o la opción Todos."""
    if valor is None:
        return True
    return str(valor).strip().lower() in {
        "", "todos", "todas", "null", "undefined"
    }


class ConsultaSalesforceViewSet(viewsets.ViewSet):
    """Listados de solo lectura, sin modelos ni una columna id artificial."""

    # Utiliza SignedUserAuthentication, definida en REST_FRAMEWORK.
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head", "options"]

    tabla = ""
    campo_fecha = ""
    filtros_exactos = {}
    campos_busqueda = ()
    orden = ""
    serializer_class = None

    def construir_filtros(self, datos, parametros):
        condiciones = []
        valores = []

        # Estos nombres de columnas vienen del código, nunca de la URL.
        for parametro, columna in self.filtros_exactos.items():
            valor = parametros.get(parametro)
            if not valor_vacio(valor):
                condiciones.append(f"[{columna}] = %s")
                valores.append(valor)

        anio = datos.get("anio")
        mes = datos.get("mes")

        if anio:
            desde = date(anio, mes or 1, 1)
            if mes and mes < 12:
                hasta = date(anio, mes + 1, 1)
            else:
                hasta = date(anio + 1, 1, 1)

            condiciones.extend([
                f"[{self.campo_fecha}] >= %s",
                f"[{self.campo_fecha}] < %s",
            ])
            valores.extend([desde, hasta])

        if datos.get("fecha_desde"):
            condiciones.append(f"[{self.campo_fecha}] >= %s")
            valores.append(datos["fecha_desde"])

        if datos.get("fecha_hasta"):
            # Incluye todo el último día, también cuando la columna es datetime.
            condiciones.append(f"[{self.campo_fecha}] < %s")
            valores.append(datos["fecha_hasta"] + timedelta(days=1))

        if datos.get("q"):
            busqueda = " OR ".join(
                f"CHARINDEX(%s, {campo}) > 0"
                for campo in self.campos_busqueda
            )
            condiciones.append(f"({busqueda})")
            valores.extend([datos["q"]] * len(self.campos_busqueda))

        where = " WHERE " + " AND ".join(condiciones) if condiciones else ""
        return where, valores

    def list(self, request):
        parametros = {
            clave: valor.strip()
            for clave, valor in request.query_params.items()
            if not valor_vacio(valor)
        }

        filtro = FiltrosConsultaSerializer(data=parametros)
        filtro.is_valid(raise_exception=True)
        datos = filtro.validated_data

        pagina = datos["page"]
        tamano = datos["page_size"]
        desplazamiento = (pagina - 1) * tamano
        where, valores = self.construir_filtros(datos, parametros)

        # Los nombres de tabla y el ORDER BY son constantes de cada ViewSet.
        # Todos los valores recibidos del front se envían como parámetros %s.
        try:
            with connections["sqlserver_meta"].cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT_BIG(*) FROM {self.tabla}{where}",
                    valores,
                )
                total = cursor.fetchone()[0]

                if pagina > 1 and desplazamiento >= total:
                    raise NotFound("La página solicitada no existe.")

                cursor.execute(
                    f"""
                    SELECT *
                    FROM {self.tabla}
                    {where}
                    ORDER BY {self.orden}
                    OFFSET %s ROWS FETCH NEXT %s ROWS ONLY
                    """,
                    valores + [desplazamiento, tamano],
                )
                columnas = [columna[0] for columna in cursor.description]
                registros = [
                    dict(zip(columnas, fila)) for fila in cursor.fetchall()
                ]
        except DatabaseError:
            logger.exception("Error al consultar Salesforce: %s", self.tabla)
            return Response(
                {"detail": "No fue posible consultar Salesforce. Intenta nuevamente."},
                status=503,
            )

        url = request.build_absolute_uri()
        siguiente = None
        anterior = None

        if desplazamiento + tamano < total:
            siguiente = replace_query_param(url, "page", pagina + 1)
        if pagina > 1:
            anterior = replace_query_param(url, "page", pagina - 1)

        serializer = self.serializer_class(registros, many=True)
        return Response({
            "count": total,
            "next": siguiente,
            "previous": anterior,
            "results": serializer.data,
        })


class OportunidadViewSet(ConsultaSalesforceViewSet):
    tabla = "[dbo].[reporte_Oportunidades_PUEBLA]"
    campo_fecha = "fecha_creacion"
    serializer_class = OportunidadSerializer
    orden = "[fecha_creacion] DESC, [nombre_oportunidad], [nombre_cuenta]"
    filtros_exactos = {
        "origen": "origen",
        "etapa": "etapa",
        "propietario_oportunidad": "propietario_oportunidad",
        "modelo_interes": "modelo_interes",
        "prueba_manejo": "prueba_manejo",
        "campana": "campaña",
        "motivo_perdida": "motivo_perdida",
    }
    campos_busqueda = (
        "[nombre_oportunidad]",
        "[nombre_cuenta]",
        "[propietario_oportunidad]",
        "[modelo_interes]",
        "[vin_vehiculo_facturado]",
    )


class ProspectoViewSet(ConsultaSalesforceViewSet):
    tabla = "[dbo].[reporte_salesforcepsptoVO_puebla]"
    campo_fecha = "Fecha_creacion"
    serializer_class = ProspectoSerializer
    orden = "[Fecha_creacion] DESC, [Apellidos], [Nombre], [Email]"
    filtros_exactos = {
        "origen": "Origen",
        "estado_lead": "Estado_lead",
        "propietario_lead": "Propietario_lead",
        "tipo_solicitud": "Tipo_Solicitud",
    }
    campos_busqueda = (
        "CONCAT([Nombre], N' ', [Apellidos])",
        "[Email]",
        "[Propietario_lead]",
        "[Descripcion]",
    )


class TareaViewSet(ConsultaSalesforceViewSet):
    tabla = "[dbo].[reporte_salesforcetareasVO_PUEBLA]"
    campo_fecha = "Fecha"
    serializer_class = TareaSerializer
    orden = "[Fecha] DESC, [Oportunidad], [Asunto], [Asignado]"
    filtros_exactos = {
        "estado": "Estado",
        "asignado": "Asignado",
        "prioridad": "Prioridad",
        "tarea": "Tarea",
        "subtipo_de_evento": "Subtipo_de_evento",
        "subtipo_de_tarea": "Subtipo_de_tarea",
        "etapa_de_la_oportunidad": "Etapa_de_la_oportunidad",
        "contacto_origen": "Contacto_Origen",
        "origen_del_prospecto_de_la_oportunidad": (
            "Origen_del_prospecto_de_la_oportunidad"
        ),
    }
    campos_busqueda = (
        "[Compañía_Cuenta]",
        "[Oportunidad]",
        "[Contacto]",
        "[Lead]",
        "[Asunto]",
        "[Nombre]",
    )
