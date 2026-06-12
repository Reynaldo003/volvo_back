#Digitales/sett.py
token = 'CBAR&RVOLKS'
whatsapp_token = 'EAAS1RWxgIcIBP8LS2l1ZAmUz4BjZCufH0VUVQCS4KQhAbAPFQtHtsbgZAVZBF8W1HjFbwur6qtN3KokHoZBY2qpZA24MafOc2bnc1SuXVK2EWT2qsGVnE4oltrQyFOYPN9rEwXFd1ZAHYvPktu7HlsoYThbThNHRwHR6PdkN8TfgZBJWEAMb1VnJsdSYSXRKegZDZD'

GRAPH_VERSION = "v22.0"
WHATSAPP_WABA_ID_DEFAULT = "TU_WHATSAPP_BUSINESS_ACCOUNT_ID"

whatsapp_url_mariana = 'https://graph.facebook.com/v22.0//messages'

whatsapp_numero_default = "52"
whatsapp_numero_mariana = "52"

WHATSAPP_LINES = {
    #whatsapp_numero_default: {
    #    "key": "default",
    #    "phone_number_id": "836147029587691",
    #    "waba_id": "1487171602543671",
    #    "access_token": whatsapp_token,
    #    "asesor_digital": "IA Vagen",
    #    "messages_url": whatsapp_url,
    #    "agencia": "VW Cordoba",
    #    "business": "Comerciales",
    #    "responder_ia": True,
    #    "template_names": ["saludo_seguimiento", "informacion_seguimiento"],
    #},

    whatsapp_numero_mariana: {
        "key": "liz",
        "phone_number_id": "1002516582953413",
        "waba_id": "1448342956973453",
        "access_token": whatsapp_token,
        "asesor_digital": "Lizbeth Cano Clara",
        "messages_url": whatsapp_url_mariana,
        "agencia": "VW Orizaba",
        "business": "Nuevos",
        "responder_ia": False,
        "template_names": ["saludo_seguimiento", "confirmacion_cita", "informacion_seguimiento"],
    },
}

WHATSAPP_PHONE_ID_TO_NUMBER = {
    str(cfg["phone_number_id"]): numero
    for numero, cfg in WHATSAPP_LINES.items()
}

WHATSAPP_TEMPLATE_UI = {
    "saludo_seguimiento": {
        "title": "Saludo de seguimiento",
        "help": "",
        "labels": {
            "body_1": "Nombre del prospecto",
            "body_2": "Interés del prospecto",
            "body_3": "Acción de seguimiento",
        },
    },
}