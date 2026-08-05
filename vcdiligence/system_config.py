from vcdiligence.database import SystemConfig

CONFIG_REGISTRY = {
    # branding
    "platform_name": {
        "value_type": "string",
        "category": "branding",
        "default": "DealScout AI",
        "description": "Nombre de la plataforma"
    },
    "theme_color": {
        "value_type": "string",
        "category": "branding",
        "default": "dark",
        "description": "Color del tema global ('dark', 'light', 'red')"
    },
    "logo_url": {
        "value_type": "string",
        "category": "branding",
        "default": "",
        "description": "URL pública o Base64 del logo"
    },
    "welcome_message": {
        "value_type": "string",
        "category": "branding",
        "default": "Bienvenido a DealScout AI",
        "description": "Mensaje de bienvenida en el login/landing"
    },
    "analysis_loading_message": {
        "value_type": "string",
        "category": "branding",
        "default": "Analizando la startup, por favor espera...",
        "description": "Mensaje de carga durante el análisis"
    },
    "analysis_complete_message": {
        "value_type": "string",
        "category": "branding",
        "default": "¡Análisis completado con éxito!",
        "description": "Mensaje al finalizar el análisis"
    },
    "footer_message": {
        "value_type": "string",
        "category": "branding",
        "default": "DealScout AI - Venture Capital Due Diligence",
        "description": "Mensaje del pie de página"
    },
    # llm_budget
    "max_tokens_per_analysis": {
        "value_type": "int",
        "category": "llm_budget",
        "default": 0,
        "description": "Límite máximo de tokens acumulados por análisis (0 = sin límite)"
    },
    "max_tokens_per_agent_call": {
        "value_type": "int",
        "category": "llm_budget",
        "default": 0,
        "description": "Límite de tokens en cada llamada individual de un agente (0 = sin límite)"
    }
}

def get_config(db, key: str):
    """
    Retrieves a config value by key. If the key is not set in the database,
    it returns the default value from CONFIG_REGISTRY, or None.
    Casts the value to the registered value_type if needed.
    """
    # Fetch from database
    cfg = db.query(SystemConfig).filter_by(key=key).first()
    if cfg:
        val_str = cfg.value
        v_type = cfg.value_type
    else:
        # Check config registry
        if key in CONFIG_REGISTRY:
            reg = CONFIG_REGISTRY[key]
            val_str = str(reg["default"])
            v_type = reg["value_type"]
        else:
            return None

    # Cast type
    if v_type == "int":
        try:
            return int(val_str)
        except ValueError:
            return 0
    elif v_type == "bool":
        return val_str.lower() in ("true", "1", "yes")
    return val_str

def set_config(db, key: str, value) -> SystemConfig:
    """
    Sets a config value in the database. Registers the metadata from
    CONFIG_REGISTRY if known, otherwise defaults to string type.
    """
    cfg = db.query(SystemConfig).filter_by(key=key).first()

    val_str = str(value)

    if key in CONFIG_REGISTRY:
        reg = CONFIG_REGISTRY[key]
        value_type = reg["value_type"]
        category = reg["category"]
        description = reg["description"]
    else:
        value_type = "string"
        category = "general"
        description = ""

    if cfg:
        cfg.value = val_str
        cfg.value_type = value_type
        cfg.category = category
        cfg.description = description
    else:
        cfg = SystemConfig(
            key=key,
            value=val_str,
            value_type=value_type,
            category=category,
            description=description
        )
        db.add(cfg)

    db.commit()
    db.refresh(cfg)
    return cfg
