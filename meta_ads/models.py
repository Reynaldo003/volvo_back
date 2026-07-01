#meta_ads/models.py
from django.db import models

class CampanaMeta(models.Model):
    id_campana = models.BigIntegerField(primary_key=True)

    id_concesionaria = models.IntegerField()
    sucursal = models.CharField(max_length=100)

    inicio_informe = models.DateField(null=True, blank=True)
    fin_informe = models.DateField(null=True, blank=True)

    nombre_campana = models.CharField(max_length=500)
    estado_campana = models.CharField(max_length=300, null=True, blank=True)
    indicador_resultados = models.CharField(max_length=300, null=True, blank=True)
    objetivo_campana = models.CharField(max_length=400, null=True, blank=True)

    inicio_campana = models.DateField(null=True, blank=True)
    fin_campana = models.DateField(null=True, blank=True)

    total_resultados = models.BigIntegerField(null=True, blank=True)

    resultados_fb = models.IntegerField(null=True, blank=True, default=0)
    resultados_ig = models.IntegerField(null=True, blank=True, default=0)
    resultados_wp = models.IntegerField(null=True, blank=True, default=0)
    resultados_masc = models.IntegerField(null=True, blank=True, default=0)
    resultados_fem = models.IntegerField(null=True, blank=True, default=0)
    resultados_sin_genero = models.IntegerField(null=True, blank=True, default=0)

    alcance = models.BigIntegerField(null=True, blank=True)
    alcance_fb = models.IntegerField(null=True, blank=True, default=0)
    alcance_ig = models.IntegerField(null=True, blank=True, default=0)
    alcance_wsp = models.IntegerField(null=True, blank=True, default=0)
    alcance_masc = models.IntegerField(null=True, blank=True, default=0)
    alcance_fem = models.IntegerField(null=True, blank=True, default=0)
    alcance_sin_genero = models.IntegerField(null=True, blank=True, default=0)

    impresiones = models.IntegerField(null=True, blank=True)
    impresiones_fb = models.IntegerField(null=True, blank=True, default=0)
    impresiones_ig = models.IntegerField(null=True, blank=True, default=0)
    impresiones_wsp = models.IntegerField(null=True, blank=True, default=0)
    impresiones_masc = models.IntegerField(null=True, blank=True, default=0)
    impresiones_fem = models.IntegerField(null=True, blank=True, default=0)
    impresiones_sin_genero = models.IntegerField(null=True, blank=True, default=0)

    tipo_presupuesto = models.CharField(max_length=50, null=True, blank=True)

    presupuesto_anuncio = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True,)
    coste_resultados = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True,)
    importe_gastado = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True,)
    importe_gastado_fb = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True,default=0,)
    importe_gastado_ig = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True,default=0,)
    importe_gastado_wsp = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True,default=0,)
    importe_gastado_masc = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True,default=0,)
    importe_gastado_fem = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True,default=0,)
    importe_gastado_sin_genero = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True,default=0,)

    edad_audiencia = models.CharField(max_length=100, null=True, blank=True)
    intereses_audiencia = models.TextField(null=True, blank=True)
    comportamiento_audiencia = models.TextField(null=True, blank=True)

    total_messaging_connection = models.IntegerField(null=True, blank=True, default=0)
    conversation_lead = models.IntegerField(null=True, blank=True, default=0)
    offsite_complete_registration_add_meta_leads = models.IntegerField(null=True, blank=True, default=0)
    page_engagement = models.IntegerField(null=True, blank=True, default=0)
    post_engagement = models.IntegerField(null=True, blank=True, default=0)
    comment = models.IntegerField(null=True, blank=True, default=0)
    offsite_content_view_add_meta_leads = models.IntegerField(null=True, blank=True, default=0)
    messaging_user_depth_2_message_send = models.IntegerField(null=True, blank=True, default=0)
    lead = models.IntegerField(null=True, blank=True, default=0)
    messaging_user_depth_3_message_send = models.IntegerField(null=True, blank=True, default=0)
    offsite_search_add_meta_leads = models.IntegerField(null=True, blank=True, default=0)
    onsite_web_lead = models.IntegerField(null=True, blank=True, default=0)
    post = models.IntegerField(null=True, blank=True, default=0)
    messaging_first_reply = models.IntegerField(null=True, blank=True, default=0)
    likes = models.IntegerField(null=True, blank=True, default=0)
    link_click = models.IntegerField(null=True, blank=True, default=0)
    messaging_conversation_started_7d = models.IntegerField(null=True, blank=True, default=0)
    lead_grouped = models.IntegerField(null=True, blank=True, default=0)
    post_reaction = models.IntegerField(null=True, blank=True, default=0)
    video_view = models.IntegerField(null=True, blank=True, default=0)
    post_unlike = models.IntegerField(null=True, blank=True, default=0)
    post_interaction_gross = models.IntegerField(null=True, blank=True, default=0)
    post_net_like = models.IntegerField(null=True, blank=True, default=0)
    photo_view = models.IntegerField(null=True, blank=True, default=0)
    post_save = models.IntegerField(null=True, blank=True, default=0)
    post_net_save = models.IntegerField(null=True, blank=True, default=0)
    messaging_user_depth_5_message_send = models.IntegerField(null=True, blank=True, default=0)
    messaging_conversation_replied_7d = models.IntegerField(null=True, blank=True, default=0)
    messaging_welcome_message_view = models.IntegerField(null=True, blank=True, default=0)

    class Meta:
        managed = False
        db_table = "campanas_meta"
        ordering = ["-inicio_informe", "-id_campana"]
        verbose_name = "Campaña Meta"
        verbose_name_plural = "Campañas Meta"

    def __str__(self):
        return f"{self.id_campana} - {self.nombre_campana}"