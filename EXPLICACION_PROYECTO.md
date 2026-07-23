# Explicación Detallada del Proyecto: DealScout AI (VCDueDiligenceAgent)

Este documento ha sido actualizado para reflejar la arquitectura de grado empresarial y las mejoras de nivel de producción introducidas en DealScout AI.

---

## 1. Crédito y Licencia (Aviso de Clonación / Bifurcación)
**Aviso importante sobre el origen del código:**
DealScout AI se basa en una bifurcación/clon del repositorio original de código abierto **[SURESHBEEKHANI/CrewAI-End-to-End](https://github.com/SURESHBEEKHANI/CrewAI-End-to-End)** bajo licencia MIT. Agradecemos y damos el crédito correspondiente al creador y equipo de desarrollo original por sentar las bases sólidas del MVP de análisis multi-agente.

Las mejoras de seguridad, autenticación, persistencia relacional, aislamiento de inquilinos (multi-tenancy), scraping defensivo y generación de PDFs marca blanca descritas en este documento son contribuciones empresariales añadidas sobre esa base original.

---

## 2. Descripción General del Proyecto
**DealScout AI** (internamente configurado como `VCDueDiligenceAgent`) es una plataforma SaaS de diligencia debida automatizada para fondos de Venture Capital, aceleradoras y sindicatos de inversión ángel. Permite a los analistas evaluar startups de forma holística a partir de su URL pública, generando reportes de inversión institucionales con puntuaciones de riesgo (0-100), sub-scores por categorías y recomendaciones de inversión claras (GO / CONDITIONAL / NO-GO).

---

## 3. Arquitectura de Grado Enterprise en Capas
Para alcanzar los estándares de confiabilidad requeridos por firmas de inversión, la arquitectura MVP original se ha transformado en un sistema robusto de 4 capas con tolerancia a fallos:

```
┌─────────────────────────────────────────────────────────┐
│                    CAPA DE PRESENTACIÓN                  │
│   Dashboard SPA Reactivo (Tailwind, Alpine.js, Glass)   │
│   Soporte White-Label, PDF, Comparación Lado a Lado     │
└────────────────────────────┬────────────────────────────┘
                             │ (HTTPS / JWT Bearer / JSON)
┌────────────────────────────▼────────────────────────────┐
│                    CAPA DE SERVICIOS API                │
│         Backend FastAPI + Seguridad JWT + Rate Limit    │
└────────────────────────────┬────────────────────────────┘
                             │ (Persistencia en DB)
┌────────────────────────────▼────────────────────────────┐
│              CAPA DE PERSISTENCIA Y COLA                │
│   SQLite/PostgreSQL + Cola de Tareas en Base de Datos   │
└────────────────────────────┬────────────────────────────┘
                             │ (Contexto Enriquecido)
┌────────────────────────────▼────────────────────────────┐
│             CAPA DE EXTRACCIÓN Y PROCESAMIENTO          │
│   Scraper requests/BS4 + Playwright headless Fallback   │
│   Integración de APIs Públicas (SEC, OpenCorporates...) │
└────────────────────────────┬────────────────────────────┘
                             │ (Cognición Multi-Agente)
┌────────────────────────────▼────────────────────────────┐
│                  CAPA DE COGNICIÓN E IA                 │
│   Orquestador CrewAI (6 Agentes Especializados)         │
│   - Senior Market Research  - Competitive Intelligence │
│   - Customer Insights       - Product Strategy         │
│   - Omission Analyst        - Lead VC Business Analyst │
└─────────────────────────────────────────────────────────┘
```

### Capa de Persistencia Relacional y Multi-Tenancy (SQLite/PostgreSQL)
El almacenamiento volátil en memoria y en disco local del MVP ha sido reemplazado por un motor ORM con SQLAlchemy:
- **Modelos de datos:** Se han modelado tablas para `organizations` (inquilinos), `users` (con roles `analista` y `administrador`), `reports` (memos de inversión guardados con sus sub-scores), `tasks` (registro persistente de tareas activas) y `audit_logs` (auditoría de accesos).
- **Aislamiento Multi-Tenancy:** Cada consulta está estrictamente filtrada por el identificador de la organización (`organization_id`). Un usuario no puede ver ni descargar reportes de otras firmas bajo ninguna circunstancia.
- **Cola de Tareas Persistente:** En lugar de un diccionario en memoria propicio a perderse ante un reinicio del servidor (por ejemplo, en el plan gratuito de Render), los estados y resultados de las tareas en segundo plano se persisten en la tabla `tasks` de la base de datos, garantizando consistencia.

### Capa de Autenticación, Seguridad y SSRF
- **Autenticación JWT:** Se implementaron flujos de login y protección de rutas mediante JSON Web Tokens firmados con algoritmo HS256 y contraseñas cifradas usando el algoritmo robusto `bcrypt`.
- **Mitigación de SSRF (Server-Side Request Forgery):** Antes de iniciar cualquier scraping, el backend valida estrictamente la URL. Resuelve las direcciones IP asociadas al dominio y bloquea cualquier IP privada (RFC 1918), loopback (localhost/127.0.0.1) o reservada para prevenir accesos no autorizados a la red interna del servidor.
- **Rate Limiting:** El endpoint `/analyze` cuenta con un limitador de velocidad que consulta el historial de auditoría de la organización en la base de datos, evitando abusos y saturaciones del sistema.

---

## 4. Flujo de Trabajo y Enriquecimiento de Datos
1. **Ingreso y Validación:** El usuario envía la URL de la startup. El sistema realiza la comprobación de SSRF y valida el rate limit.
2. **Caché en Base de Datos:** Si el reporte ya fue evaluado por la organización, se recupera de inmediato desde la base de datos en menos de 50ms.
3. **Consulta de Fuentes Públicas Reales:** El backend consulta concurrentemente en tiempo real:
   - **SEC EDGAR:** Registros y Form D de financiamiento privado.
   - **OpenCorporates:** Datos de registro societario y estado legal.
   - **USPTO:** Existencia de marcas y patentes registradas.
   - **CourtListener (RECAP):** Litigios federales públicos de la empresa o fundadores.
   - **GitHub API:** Actividad de repositorios públicos del equipo técnico.
4. **Scraping Adaptativo con Playwright:** El scraper intenta requests estáticos. Si falla o es bloqueado (ej. Cloudflare/SPA), activa automáticamente un navegador Playwright headless en segundo plano para renderizar el Javascript de la startup de manera transparente.
5. **Detección Explícita de Omisiones:** Cuando una página o API no se puede verificar, el sistema lo registra como tal (`[Could not verify X]`) en lugar de permitir que el LLM invente información.
6. **Ejecución de la Red de Agentes (CrewAI):** Se alimentan las 6 misiones con todo el HTML scrapeado y el JSON enriquecido de las APIs públicas.
7. **El Nuevo Agente: Omission Analyst:** Un agente especializado evalúa el contexto contrastándolo con checklists por industria/etapa y redacta la sección **"Señales por Ausencia"**, analizando además la densidad de lenguaje vago (superlativos sin sustento) frente a datos numéricos reales.
8. **Generación de Reporte PDF Marca Blanca:** Los resultados se compilan en un PDF de alta calidad con la biblioteca ReportLab, incorporando el nombre y logotipo configurados por el administrador de la organización.

---

## 5. El Equipo de 6 Agentes CrewAI
1. **Senior Market Research Specialist:** Sizing (TAM/SAM/SOM), macro-tendencias y análisis regulatorio.
2. **Competitive Intelligence Analyst:** Gaps de mercado y matrices de competidores.
3. **Customer Insights Researcher:** Personas de compradores, canales de adquisición y disposición de pago.
4. **Product Strategy Advisor:** Roadmaps de producto, arquitectura y viabilidad técnica.
5. **Omission Analyst (Nuevo):** Analiza ausencias críticas de información de negocio, bios, pricing y densidades de lenguaje.
6. **Lead Venture Capital Business Analyst:** Consolida todos los hallazgos en el Memorándum final, calcula los sub-scores por categorías (Mercado, Equipo, Producto, Tracción, Riesgos) y emite la recomendación definitiva.

---

## 6. Variables de Entorno y Configuración
| Variable | Descripción | Valor por defecto |
|---|---|---|
| `LLM_PROVIDER` | Proveedor principal de LLM (`openrouter` \| `grok` \| `openai`) | `openrouter` |
| `API_KEY_OPENROUTER` | API Key para la plataforma OpenRouter | Opcional |
| `API_KEY_GROK` | API Key para la consola de desarrollador de xAI | Opcional |
| `API_KEY_OPENAI` | API Key estándar para la plataforma OpenAI | Opcional |
| `DATABASE_URL` | URL de base de datos relacional (PostgreSQL en producción) | `sqlite:///vcdiligence.db` |
| `JWT_SECRET` | Firma de seguridad para tokens JWT de sesión | Clave autogenerada |
| `ENV` | Entorno de despliegue (`production` para deshabilitar reload) | `development` |

---

## 7. Instrucciones de Instalación y Ejecución local

1. Instalar dependencias requeridas del sistema y de Playwright:
   ```bash
   pip install -e .
   playwright install chromium
   ```

2. Inicializar y poblar la base de datos con los usuarios semilla:
   ```bash
   python -m vcdiligence.seed
   ```

3. Arrancar el servidor web:
   ```bash
   vcdiligence
   ```
   Abre tu navegador en `http://localhost:10000` e ingresa con:
   - Email: `analyst@dealscout.ai`
   - Password: `analystpassword`
