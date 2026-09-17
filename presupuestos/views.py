from django.db.models import Q

from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated

from usuarios.authentication import SignedUserAuthentication

from .models import MatrizPresupuesto, MatrizPresupuestoRef
from .serializers import (
    MatrizPresupuestoRefSerializer,
    MatrizPresupuestoSerializer,
)


DB_ALIAS = "sqlserver_presupuestos"


class PresupuestosPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000


class MatrizPresupuestosListView(ListAPIView):
    authentication_classes = [SignedUserAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = MatrizPresupuestoSerializer
    pagination_class = PresupuestosPagination

    def get_queryset(self):
        qs = (
            MatrizPresupuesto.objects
            .using(DB_ALIAS)
            .all()
            .order_by("-nr_orcamento")
        )

        params = self.request.query_params

        agencia = (params.get("agencia") or "").strip()
        nr_orcamento = (params.get("nr_orcamento") or "").strip()
        search = (params.get("search") or "").strip()
        sit = (params.get("sit") or "").strip()

        if agencia:
            qs = qs.filter(agencia__iexact=agencia)

        if nr_orcamento:
            try:
                qs = qs.filter(nr_orcamento=int(nr_orcamento))
            except ValueError:
                return qs.none()

        if sit:
            qs = qs.filter(sit__iexact=sit)

        if search:
            qs = qs.filter(
                Q(nome__icontains=search)
                | Q(placa_veic__icontains=search)
                | Q(chassi__icontains=search)
                | Q(cod_modelo__icontains=search)
                | Q(cgc__icontains=search)
            )

        return qs


class MatrizPresupuestosRefListView(ListAPIView):
    authentication_classes = [SignedUserAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = MatrizPresupuestoRefSerializer
    pagination_class = PresupuestosPagination

    def get_queryset(self):
        qs = (
            MatrizPresupuestoRef.objects
            .using(DB_ALIAS)
            .all()
            .order_by("-nr_orcamento", "rowid")
        )

        params = self.request.query_params

        agencia = (params.get("agencia") or "").strip()
        nr_orcamento = (params.get("nr_orcamento") or "").strip()
        search = (params.get("search") or "").strip()

        if agencia:
            qs = qs.filter(agencia__iexact=agencia)

        if nr_orcamento:
            try:
                qs = qs.filter(nr_orcamento=int(nr_orcamento))
            except ValueError:
                return qs.none()

        if search:
            qs = qs.filter(
                Q(cod_prod__icontains=search)
                | Q(nm_prod__icontains=search)
                | Q(coment_ref__icontains=search)
            )

        return qs