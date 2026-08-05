# DealScout AI — Multi-Agent Venture Capital Due Diligence & Investment Directory

Nota Importante: Solo necesita una sola API Key de Inteligencia Artificial para funcionar. El sistema está hecho tanto para funcionar de forma eficiente a bajo consumo (por ejemplo, en un entorno Render gratuito manteniendo un rendimiento estable y seguro), como para correr en servidores de mayor potencia. El cambio de potencia lo hace significativamente veloz y está diseñado para adaptarse con pocos recursos.

DealScout AI (configurado como `VCDueDiligenceAgent`) es un motor autónomo de due diligence para Venture Capital de nivel empresarial y un directorio interactivo bidireccional. Desarrollado con **FastAPI**, **SQLAlchemy** y **CrewAI**, automatiza el proceso de análisis de startups a partir de URLs públicas, Pitch Decks (PDF/PPTX) o perfiles de LinkedIn. Actúa como un sistema completo de soporte de decisiones, generando reportes de inversión PDF white-label personalizables, puntajes de readiness (0-100) y un directorio seguro para conectar fundadores con compradores e inversores calificados.

---

## 🌟 Core Features

- **Autonomous Multi-Agent Cognition:** Orquestación coordinada de un equipo de 7 agentes especializados de CrewAI que investigan, analizan, debaten y compilan el memorando de inversión final.
- **Dual-Sided Marketplace Directory:** Conecta de forma segura a Fundadores (que buscan inversión o están abiertos a adquisición) con Compradores/Inversores (VCS, ángeles independientes y analistas de desarrollo corporativo).
- **Adaptive Scraper (Playwright fallback):** Un motor de scraping robusto que combina la velocidad de la extracción tradicional con `requests/BS4` con un navegador **Playwright headless Chromium** cargado bajo demanda solo cuando es necesario renderizar JavaScript pesado o evadir SPAs complejas.
- **Live External API Integration:** Acceso en tiempo real a bases de datos de producción reales para obtener registros corporativos (OpenCorporates, SEC EDGAR Form D), patentes (USPTO), antecedentes de litigios legales (CourtListener), estado de sanciones internacionales (OFAC SDN List con fuzzy matching local) y actividad tecnológica (GitHub API).
- **White-Label Customization & SystemConfig:** Panel administrativo centralizado donde se configuran dinámicamente variables visuales (colores de tema, mensajes de bienvenida/carga, nombres de plataforma) y límites de consumo sin necesidad de redeploy. Reportes ReportLab PDF generados con logos corporativos de alta resolución en tiempo real.
- **Continuous Monitoring:** Escaneo automatizado periódico (usando un cron scheduler interno en APScheduler) para registrar y notificar cambios de puntaje, novedades legales y actualizaciones técnicas de las startups monitoreadas.
- **Pool de API Keys con Rotación Automática (`ApiKeyPool`):** Gestión de múltiples llaves API de LLM de forma inteligente. Si una llave devuelve un error de rate-limit o falta de crédito, el sistema la marca temporalmente, rota automáticamente a otra llave saludable y un worker en segundo plano intenta recuperarla de forma autónoma cada 6 horas.
- **Privacy-First Testimonial Engine:** Carrusel de feedback y testimonios de usuarios con consentimiento granular para compartir comentarios, nombres y fotos. Los testimonios con capturas de pantalla adjuntas se guardan en un buzón de moderación pendiente de aprobación del administrador.
- **SSRF Mitigations & Rate-Limiting:** Políticas de protección listas para producción que validan direcciones IP públicas, bloqueando accesos a entornos internos de red (SSRF) y limitación de peticiones de análisis concurrentes.

---

## 📊 Diagramas de Flujo del Sistema

### 1. Pipeline Cognitivo Multi-Agente (7 Agentes)
El siguiente diagrama detalla cómo los 5 agentes especialistas analizan de manera secuencial y estructurada la información de la startup devolviendo esquemas Pydantic `AgentFinding`, y cómo confluyen en el Business Analyst y el Devil's Advocate para generar el veredicto final:

```mermaid
graph TD
    A[Inicio del Crew] --> B[Market Research Specialist<br/>'AgentFinding' estructurado]
    B --> C[Competitive Intelligence Analyst<br/>'AgentFinding' estructurado]
    C --> D[Customer Insights Researcher<br/>'AgentFinding' estructurado]
    D --> E[Product Strategy Advisor<br/>'AgentFinding' estructurado]
    E --> F[Omission Analyst<br/>'AgentFinding' estructurado]

    F --> G[Business Analyst<br/>Sintetiza hallazgos en prosa completa/memo]
    G --> H[Devil's Advocate<br/>Debate/Contraargumenta resultado final]
    H --> I[Memo de Inversión Final Combinado]

    style B fill:#1e293b,stroke:#22d3ee,stroke-width:2px,color:#fff
    style C fill:#1e293b,stroke:#22d3ee,stroke-width:2px,color:#fff
    style D fill:#1e293b,stroke:#22d3ee,stroke-width:2px,color:#fff
    style E fill:#1e293b,stroke:#22d3ee,stroke-width:2px,color:#fff
    style F fill:#1e293b,stroke:#22d3ee,stroke-width:2px,color:#fff
    style G fill:#0f172a,stroke:#34d399,stroke-width:2px,color:#fff
    style H fill:#0f172a,stroke:#34d399,stroke-width:2px,color:#fff
    style I fill:#020617,stroke:#e2e8f0,stroke-width:3px,color:#fff
```

### 2. Flujo del Ciclo de Vida de una Petición de Análisis
Este diagrama de secuencia ilustra el flujo de extremo a extremo que experimenta una solicitud de análisis iniciada por un usuario:

```mermaid
graph TD
    User([Usuario envía URL / Pitch Deck]) --> Scraper[SmartScraper<br/>Extrae contenido web/PDF/PPTX]
    Scraper --> Orch[Source Orchestrator<br/>Consulta fuentes concurrentemente con ThreadPool]
    Orch --> SEC[SEC EDGAR Form D]
    Orch --> Court[CourtListener]
    Orch --> USPTO[Patentes USPTO]
    Orch --> GH[GitHub API]
    Orch --> OFAC[Fuzzy Sanctions OFAC]

    SEC & Court & USPTO & GH & OFAC --> MergeCtx[Fusión de Contexto & Inputs]
    MergeCtx --> Crew[Orquestador de Agentes CrewAI]
    Crew --> GenPDF[Generador PDF White-Label<br/>pdf_generator.py]
    GenPDF --> Notify[Notificaciones SMTP / Alerta Admin WhatsApp]
    Notify --> Finished([Reporte Listo en Dashboard])
```

---

## 🖥️ Interfaz de Usuario (Descripción de Pantallas)

Dado que no es posible desplegar recursos estáticos en vivo durante la compilación del repo, a continuación se describe brevemente la experiencia visual y estructural de cada pantalla principal del sistema:

1. **Pantalla de Login / Registro:** Presenta una interfaz oscura elegante con el mensaje de bienvenida dinámico configurado por el administrador (`welcome_message`), campos para ingresar correo y contraseña, y una opción rápida para registrarse como inversor (personal) o fundador (empresa) con código de invitación/referido si posee.
2. **Dashboard de Análisis (Founder / Investor):**
   - **Para Inversionistas:** Permite buscar startups ingresando el nombre de la compañía, URL directa o LinkedIn. Muestra una lista de análisis completados con su Readiness Score, recomendación de inversión (GO/CONDITIONAL/NO-GO), botones para descargar el reporte PDF, realizar comparación múltiple, y activar monitoreo continuo.
   - **Para Fundadores:** Permite ver los resultados de su propio análisis, configurar su listado público en el directorio de inversión, subir su Pitch Deck o actualizar su perfil de empresa con dominio verificado.
3. **Panel Administrativo (Admin Console):** Secciones dedicadas para que los administradores editen las variables del sistema (`SystemConfig`) en tiempo real (por ejemplo, presupuestos de tokens o switch de pasarela de pagos), ver el estado detallado de las llaves del pool (`api_key_pools`) y sus consecutivas fallas de conexión, moderar testimonios con capturas, examinar logs de errores, y verificar manualmente cuentas de empresas (`verified_by_admin = true`).

---

## 🛠 Directory and Account Types ("Buyer vs Founder")

El sistema separa las cuentas e interacciones en dos flujos completamente aislados:

### 1. Tipos de Cuentas
- **Personal / Investor Accounts:** Diseñado para analistas de VC, ángeles y compradores independientes. Tienen acceso total para iniciar análisis de cualquier startup, comparar múltiples memos, registrar y calibrar sus decisiones de inversión basadas en scores personalizados, y expresar interés en startups del directorio.
- **Empresa / Founder Accounts:** Diseñado para fundadores y ejecutivos de startups. Tienen acceso al análisis enfocado en su propia empresa, la opción de publicarse en el directorio público y renovar la expiración de sus publicaciones.
- **Verificación de Dominio:** Si un fundador se registra con un correo corporativo que coincide con el dominio oficial de su startup (ej. `founder@stripe.com` para `stripe.com`), su cuenta es automáticamente marcada como `verified_domain = true`.

### 2. Directorio Bidireccional y Contacto Seguro ("Me interesa")
- **Consentimiento de Publicación (Opt-In):** Ninguna startup analizada se publica automáticamente. Los fundadores deben configurar explícitamente sus parámetros de listado (categoría, descripción de visibilidad, y decidir si mostrar su score numérico exacto o una insignia cualitativa de rendimiento).
- **Moderación:** Las solicitudes se guardan como `pending_review` y requieren aprobación manual de un administrador para ser visibles públicamente.
- **Lead Generation Seguro:** El correo directo del fundador permanece oculto para evitar spam. Cuando un inversor autenticado hace clic en **"Me interesa"**, el sistema registra la solicitud en `ListingInterest` y despacha un correo de alerta SMTP seguro directamente al fundador con los datos del inversor interesado.
- **Expiración de Listados:** Los anuncios expiran de manera automática a los 60 días. El sistema envía notificaciones previas por correo con un enlace seguro de renovación rápida de un solo clic.

---

## ⚙️ Configuración y Variables de Entorno

### 1. Variables de Entorno Requeridas en Arranque (.env)
A diferencia de los ajustes de diseño configurables desde el Panel de Admin, estas claves de bajo nivel son requeridas en la inicialización:

| Variable | Descripción | Default / Opción |
|---|---|---|
| `DATABASE_URL` | String de conexión relacional | `sqlite:///vcdiligence.db` |
| `JWT_SECRET` | Clave secreta para firma de tokens JWT (Mandatorio, la app falla si está vacío) | Debe configurarse |
| `ENV` | Modo de entorno del servidor | `development` \| `production` |
| `MIN_USERS_TO_SHOW_STATS` | Límite mínimo de usuarios para visualizar estadísticas de landing | `20` |
| `LISTING_EXPIRY_DAYS` | Vigencia de un listado de inversión pública antes de expirar | `60` |
| `SMTP_HOST` / `SMTP_PORT` | Configuración del servidor de alertas SMTP | `smtp.gmail.com` \| `587` |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | Credenciales de correo de alertas | Opcional |

### 2. Configuración Centralizada en Base de Datos (SystemConfig)
Estas propiedades se guardan directamente en la tabla `SystemConfig` y pueden ser modificadas en vivo por los administradores desde el panel visual:

- **Configuración de Marca (Branding):**
  - `platform_name`: Nombre visible del portal (por defecto `DealScout AI`).
  - `theme_color`: Estilo CSS principal (`dark`, `light`, `red`).
  - `logo_url`: Enlace público o string Base64 del logo corporativo institucional.
  - `welcome_message`: Mensaje de portada en landing/login.
  - `analysis_loading_message`: Mensaje desplegado durante el scraping y análisis de agentes.
  - `analysis_complete_message`: Leyenda de finalización exitosa.
  - `footer_message`: Pie de página global del portal.
- **Presupuestos y Consumos (LLM Budget):**
  - `max_tokens_per_analysis`: Presupuesto acumulativo de tokens consumidos por todo el grupo de agentes en una sola corrida (0 = sin límite). Si se supera, se cancela la ejecución inmediatamente levantando un `TokenBudgetExceededError` para evitar sobrefacturación sin afectar la salud de la API Key.
  - `max_tokens_per_agent_call`: Límite máximo de tokens de respuesta permitido para cada consulta individual de un especialista (0 = sin límite).

---

## 🧩 Directory Map and Repository Layout

- `vcdiligence/app.py`: Aplicación FastAPI principal que administra los endpoints REST, políticas de autenticación, moderación, carga de Pitch Decks, webhooks de pagos (Stripe, Crypto) y renderizado de plantillas HTML.
- `vcdiligence/database.py`: Definiciones SQLAlchemy de todas las tablas e índices del sistema. Gestiona la inicialización segura e inyección programática de migraciones Alembic.
- `vcdiligence/system_config.py`: Definición de CONFIG_REGISTRY de configuración dinámica. Métodos seguros para leer (`get_config`) y escribir (`set_config`) valores tipados y validados.
- `vcdiligence/agent_schemas.py`: Contiene el esquema Pydantic estructurado de `AgentFinding` utilizado para restringir el formato de salida JSON de los agentes analistas.
- `vcdiligence/crew.py`: Implementación del pipeline cognitivo CrewAI. Controla los callbacks de registro de consumo de tokens y el loop inteligente de rotación `run_crew_with_rotation()`.
- `vcdiligence/scraper.py`: Adaptador inteligente `SmartScraper` encargado de extraer texto de portales, PDFs de Pitch Decks, presentaciones PPTX y perfiles de LinkedIn.
- `vcdiligence/public_apis.py`: Integración de conectores externos (SEC EDGAR, CourtListener, USPTO, GitHub API) y caché de consultas.
- `vcdiligence/pdf_generator.py`: Generador ReportLab que maquilla el memo técnico final de prosa e incluye branding white-label en el archivo descargable.
- `vcdiligence/tasks.py`: Módulo que consume las tareas asíncronas en segundo plano por medio de FastAPI BackgroundTasks.
- `vcdiligence/monitoring.py`: Worker recurrente de APScheduler que corre análisis de cambios recurrentes, actualiza el estatus de las llaves bloqueadas del pool y expira publicaciones antiguas.
- `vcdiligence/validator.py`: Capa de seguridad que audita SSRF y deniega conexiones a rangos privados/locales de IP.

---

## 🚀 Quick Start & Instalación

### 1. Clonar el Repositorio e Instalar Dependencias
Asegúrate de contar con Python y Poetry instalado en tu máquina de desarrollo:
```bash
git clone https://github.com/SURESHBEEKHANI/CrewAI-End-to-End.git DealScoutAI
cd DealScoutAI
poetry install
poetry run playwright install chromium
```

### 2. Configurar el Archivo de Entorno
Copia la plantilla y configura tu secreto y llaves API correspondientes:
```bash
cp .env.example .env
```
*(Asegúrate de asignar una clave fuerte en `JWT_SECRET` para evitar que la aplicación falle en el arranque)*

### 3. Ejecutar las Migraciones Iniciales de Alembic
El sistema aplicará automáticamente todas las tablas al iniciar la aplicación, pero también puedes ejecutarlas o comprobarlas manualmente mediante:
```bash
poetry run alembic upgrade head
```

### 4. Alimentar Datos de Prueba (Seeding)
Inserta datos iniciales de prueba (usuarios analistas, administradores, configuraciones del CONFIG_REGISTRY y claves API mock):
```bash
poetry run python -m vcdiligence.seed
```

### 5. Iniciar la Aplicación
```bash
poetry run python -m vcdiligence.app
```
La aplicación estará disponible en `http://localhost:10000`.

- **Analista de Prueba:** `analyst@dealscout.ai` / `analystpassword`
- **Administrador de Prueba:** `admin@dealscout.ai` / `adminpassword`

---

## 🧪 Pruebas Unitarias e Integración

Para ejecutar la batería completa de pruebas automatizadas y asegurar que no existan regresiones de base de datos o lógica:
```bash
poetry run python -m unittest discover -s tests
```

---

## ⚡ Optimización de Recursos

El sistema se diseñó de manera ágil e inteligente para operar con mínima sobrecarga:
- **Modelo de LLM Unificado:** Funciona consumiendo **únicamente** un proveedor configurado a la vez, simplificando radicalmente costos.
- **Navegador Playwright Bajo Demanda:** Solo levanta y arranca el motor Chromium headless si la extracción HTML inicial mediante `requests` detecta SPAs o firewalls pesados. El navegador se destruye inmediatamente al terminar para liberar memoria RAM.
- **SMTP Seguro Integrado:** La entrega de correos se ejecuta a nivel de función nativa sin requerir workers pesados corriendo continuamente en segundo plano.

---

## 👨‍💻 Creador

**DealScout AI** es un proyecto creado y mantenido por **[Marlon Baez Mendez](https://github.com/athenacoree/MARLON-BAEZ-MENDEZ-)**.

Para más información sobre el autor, consulta su [bibliografía oficial](https://github.com/athenacoree/MARLON-BAEZ-MENDEZ-).
