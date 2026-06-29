#volvo
#Digitales/sett.py
token = 'PBAR&RVOLVO'
whatsapp_token = 'EAAOw8lmcSSEBRni7VfZCjzFapQI2szs6GNaImaXQqXDbVYJqjGPZBrVGHPme6GG1LHWECkBwyQXZA1m1MfIFkuVMssZCyDwwi3KiUbPk0McRZB1KQuVFtKPsgiH4QRrHI9CycW219FNKIg4SvTwYtR96NZA6Qe4xBqLqkH6bgjQgmnSLOaXm5QLwzsc6IY8VkLXgZDZD'

GRAPH_VERSION = "v22.0"
WHATSAPP_WABA_ID_DEFAULT = "1520374786158708"

whatsapp_url_mariana = 'https://graph.facebook.com/v22.0/1209013795622558/messages'
whatsapp_numero_default = "522211092815"
whatsapp_numero_mariana = "522211092815"
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
        "phone_number_id": "1209013795622558",
        "waba_id": "1520374786158708",
        "access_token": whatsapp_token,
        "asesor_digital": "Mariana Tlamani",
        "messages_url": whatsapp_url_mariana,
        "agencia": "Volvo",
        "business": "Nuevos",
        "responder_ia": False,
        "template_names": ["confirmacion_prueba_manejo","prospectos_salesforce_solicitud","prospecto_salesforce_testdrive","2do_contacto_cotizacion_salesforce",],
    },
}

WHATSAPP_PHONE_ID_TO_NUMBER = {
    str(cfg["phone_number_id"]): numero
    for numero, cfg in WHATSAPP_LINES.items()
}

WHATSAPP_TEMPLATE_UI = {
    "confirmacion_prueba_manejo": {
        "title": "Confirmación Prueba Manejo",
        "help": "",
        "labels": {
            "body_1": "Hora de la cita",
            "body_2": "Nombre del consultor",
        },
    },

    "prospectos_salesforce_solicitud": {
        "title": "Solicitud Salesforce",
        "help": "",
        "labels": {
            "body_1": "Nombre",
        },
        "header": {
            "type": "image",
            "link": "https://crmvolvo.grupoautomotrizryr.com/media/plantillas/salesforce_solicitud.jpeg",
        },
    },

    "prospecto_salesforce_testdrive": {
        "title": "Prueba de Manejo Salesforce",
        "help": "",
        "labels": {
            "header_1": "Nombre",
        },
    },

    "2do_contacto_cotizacion_salesforce": {
        "title": "Segundo Contacto Cotización Salesforce",
        "help": "",
        "labels": {
            "header_1": "Nombre",
        },
    },
}