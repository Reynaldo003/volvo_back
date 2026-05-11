#Digitales/sett.py
token = 'CBAR&RVOLKS'
whatsapp_token = 'EAAS1RWxgIcIBP8LS2l1ZAmUz4BjZCufH0VUVQCS4KQhAbAPFQtHtsbgZAVZBF8W1HjFbwur6qtN3KokHoZBY2qpZA24MafOc2bnc1SuXVK2EWT2qsGVnE4oltrQyFOYPN9rEwXFd1ZAHYvPktu7HlsoYThbThNHRwHR6PdkN8TfgZBJWEAMb1VnJsdSYSXRKegZDZD'
whatsapp_token_tuxtepec = 'EAAVlkKROgagBRdZAyzfeyZAQL0ZBwGZBSOunNx57FoXkLzTdDeA54vOBMOZCge18ttvMvprzSybCySol3ZBzCiAkfJLJzbN6bX0ISHlRl4JoTmYc1p09A4HM3MT7ZAiVFLTAXfKxFll9HNuDTVkZAHluYqYZB5sdZBlkuMBQsJd9GD4ZBmymlFwM60kBEF0VhMAjgZDZD'
META_ADS_ACCESS_TOKEN = 'EAAzEBRucbwUBRBhOmARz4wwH6bcgslaww637yC7eoaTWxnoezzGwW6ZCUrWW8EOmKSZASApvAuP0fqjnxBtyPAyKlPDIxCwrTWfLa86rbkYiCMTpAxERA1ZC8Xrke2ivx2mVFVN7R5dYUG3WcZCwxNoSATZCLBYrDGGj6vZAb7a36ZCGZC12HYRN3mvumQwyAliOOCaCGFx8Met3RKQ74cHH'


GRAPH_VERSION = "v22.0"
WHATSAPP_WABA_ID_DEFAULT = "TU_WHATSAPP_BUSINESS_ACCOUNT_ID"

whatsapp_url = 'https://graph.facebook.com/v22.0/836147029587691/messages'
whatsapp_url_liz = 'https://graph.facebook.com/v22.0/1002516582953413/messages'
whatsapp_url_eren = 'https://graph.facebook.com/v22.0/970758852797236/messages'
whatsapp_url_bianca = 'https://graph.facebook.com/v22.0/1118159131375259/messages'
whatsapp_url_denisse = 'https://graph.facebook.com/v22.0/1134322799754327/messages'
whatsapp_url_marelly = 'https://graph.facebook.com/v22.0/1113085168553604/messages'

whatsapp_numero_default = "522712638803"
whatsapp_numero_liz = "522721111244"
whatsapp_numero_eren = "522713133332"
whatsapp_numero_bianca = "522712837999"
whatsapp_numero_denisse = "522721986539"
whatsapp_numero_marelly = "522871232641"

WHATSAPP_LINES = {
    whatsapp_numero_default: {
        "key": "default",
        "phone_number_id": "836147029587691",
        "waba_id": "1487171602543671",
        "access_token": whatsapp_token,
        "asesor_digital": "IA Vagen",
        "messages_url": whatsapp_url,
        "agencia": "VW Cordoba",
        "business": "Comerciales",
        "responder_ia": True,
        "template_names": ["saludo_seguimiento", "informacion_seguimiento"],
    },

    whatsapp_numero_liz: {
        "key": "liz",
        "phone_number_id": "1002516582953413",
        "waba_id": "1448342956973453",
        "access_token": whatsapp_token,
        "asesor_digital": "Lizbeth Cano Clara",
        "messages_url": whatsapp_url_liz,
        "agencia": "VW Orizaba",
        "business": "Nuevos",
        "responder_ia": False,
        "template_names": ["saludo_seguimiento", "confirmacion_cita", "informacion_seguimiento"],
    },

    whatsapp_numero_eren: {
        "key": "eren",
        "phone_number_id": "970758852797236",
        "waba_id": "2822606908081116",
        "access_token": whatsapp_token,
        "asesor_digital": "Erendira Santos Coyotzi",
        "messages_url": whatsapp_url_eren,
        "agencia": "VW Cordoba",
        "business": "Nuevos",
        "responder_ia": False,
        "template_names": ["saludo_seguimiento", "informacion_seguimiento"],
    },

    whatsapp_numero_bianca: {
        "key": "bianca",
        "phone_number_id": "1118159131375259",
        "waba_id": "1674154250377394",
        "access_token": whatsapp_token,
        "asesor_digital": "Bianca Chavez Alarcon",
        "messages_url": whatsapp_url_bianca,
        "agencia": "VW Cordoba Usados",
        "business": "Usados",
        "responder_ia": False,
        "template_names": ["saludo_seguimiento", "informacion_seguimiento"],
    },

    whatsapp_numero_denisse: {
        "key": "denisse",
        "phone_number_id": "1134322799754327",
        "waba_id": "1512733033596137",
        "access_token": whatsapp_token,
        "asesor_digital": "Candy Denisse Marquez",
        "messages_url": whatsapp_url_denisse,
        "agencia": "VW Orizaba Usados",
        "business": "Usados",
        "responder_ia": False,
        "template_names": ["saludo_seguimiento", "informacion_seguimiento"],
    },

    whatsapp_numero_marelly: {
        "key": "marelly",
        "phone_number_id": "1113085168553604",
        "waba_id": "1447380546688132",
        "access_token": whatsapp_token_tuxtepec,
        "asesor_digital": "Marelly Tenorio Salinas",
        "messages_url": whatsapp_url_marelly,
        "agencia": "VW Tuxtepec",
        "business": "Nuevos",
        "responder_ia": False,
        "template_names": ["saludo_seguimiento", "informacion_seguimiento"],
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
    "informacion_seguimiento": {
        "title": "Seguimiento",
        "help": "",
        "labels": {
            "body_1": "usuario",
            "body_2": "instalaciones",
            "body_3": "experiencia",
            "body_4": "de",
        },
    },
}