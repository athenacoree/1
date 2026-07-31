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

### Capa de Persistencia Relacional, Cola de Tareas Integrada y Multi-Tenancy (SQLite/PostgreSQL)
El almacenamiento volátil en memoria y en disco local del MVP ha sido reemplazado por un motor ORM con SQLAlchemy:
- **Modelos de datos:** Se han modelado tablas para `organizations` (inquilinos), `users` (con roles `analista` y `administrador`), `reports` (memos de inversión guardados con sus sub-scores), `tasks` (registro persistente de tareas activas) y `audit_logs` (auditoría de accesos).
- **Aislamiento Multi-Tenancy:** Cada consulta está estrictamente filtrada por el identificador de la organización (`organization_id`). Un usuario no puede ver ni descargar reportes de otras firmas bajo ninguna circunstancia.
- **Cola de Tareas Ligera con FastAPI BackgroundTasks:** Hemos simplificado la infraestructura eliminando las dependencias externas de Celery y Redis. Ahora, el análisis asíncrono se orquesta a través de `BackgroundTasks` de FastAPI directamente integrado con la tabla `tasks` en la base de datos relacional. Los estados (`starting`, `scraping`, `analyzing`, `debating`, `completed`, `failed`) y progresos se persisten y actualizan de forma continua, facilitando un polling reactivo desde el frontend sin sobrecargar el servidor.

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
4. **Scraping Adaptativo con Playwright (Lazy Load):** El scraper intenta requests estáticos. Si falla o es bloqueado (ej. Cloudflare/SPA), activa automáticamente un navegador Playwright headless en segundo plano para renderizar el Javascript de la startup de manera transparente. Las dependencias del navegador e inicialización de Playwright están optimizadas mediante "Lazy Loading" (carga perezosa), importándose únicamente cuando el fallback se activa en lugar de hacerlo durante el arranque global de la aplicación.
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

## 6. Nuevas Formas de Iniciar un Análisis (Entry Modes)
Para enriquecer la experiencia de usuario y agilizar la diligencia debida, se han incorporado cuatro métodos flexibles de entrada en la interfaz de usuario:
1. **Por URL:** Entrada tradicional para iniciar el scraping asíncrono directo de un dominio de internet.
2. **Por Nombre de Empresa:** Un buscador semántico integrado (`POST /search-company`) que localiza en DuckDuckGo hasta 3 candidatos corporativos oficiales (con logos y favicons dinámicos) y permite confirmar cuál se desea analizar antes de disparar el flujo completo.
3. **Por Perfil de LinkedIn:** Soporte para perfiles de empresas o fundadores en LinkedIn. El scraper de backend (`SmartScraper.scrape_linkedin`) extrae datos esenciales (sector, tamaño de equipo) mediante DuckDuckGo y los pasa como contexto de agentes, infiriendo de forma autónoma el sitio web oficial.
4. **Por Subida de Pitch Deck:** Carga directa multipart (`POST /analyze/upload`) de presentaciones en formato PDF o PPTX. Utilizando las bibliotecas ligeras `pypdf` y `python-pptx`, se extrae el texto corporativo de forma instantánea, se detectan enlaces internos mediante expresiones regulares para definir el dominio objetivo y se pasa todo el pitch deck estructurado como contexto enriquecido a la red de agentes de CrewAI.

## 7. Notificaciones de Finalización por Correo
Cuando finaliza un análisis en segundo plano, DealScout AI envía automáticamente una notificación de correo por SMTP al usuario (`send_report_ready_email`) detallando el nombre de la startup analizada, el score final de inversión y un enlace directo con token JWT de query parameter para descargar el reporte PDF sin requerir logins manuales recurrentes.

## 8. Landing Pública, Validación y Funciones de Confianza (Nuevas Características)
Hemos introducido una suite completa de validación, prueba social y canales directos para dinamizar la fase inicial de lanzamiento:
1. **Banner de Fase de Validación:** Un aviso visible pero no invasivo en la landing page pública indica que el sistema se encuentra en fase de validación/producción temprana, mostrando transparencia y atrayendo adoptantes iniciales.
2. **Contadores Públicos Condicionales:** Se despliega un bloque de estadísticas agregadas (total de usuarios, split de cuentas personal vs. empresa y cantidad de compañías analizadas). Estas estadísticas solo se visualizan si superan un umbral mínimo configurable (`MIN_USERS_TO_SHOW_STATS`, default 20), evitando verse vacías en los primeros días.
3. **Sistema de Testimonios Estrictamente Opt-In:** Formulario de feedback donde el usuario decide activamente qué información compartir públicamente (su comentario, su foto de perfil, o su nombre/empresa). Ninguna casilla se auto-marca por defecto, protegiendo la privacidad. Los comentarios aprobados se rotan aleatoriamente en un carrusel público.
4. **Moderación de Capturas y Fotos de Perfil:** Los testimonios con captura de pantalla (ej. reseñas de Twitter/LinkedIn) quedan en estado `pending_review` y requieren aprobación manual del administrador desde un panel de control antes de mostrarse en la landing.
5. **Verificación de Empresas:** Las cuentas corporativas comparan automáticamente el dominio del correo de registro con el sitio web confirmado (ej. `juan@acme.com` vs `acme.com`), asignándoles la insignia `verified_domain = true`. El administrador puede verificar manualmente una cuenta VIP (`verified_by_admin = true`).
6. **Entrega de Reporte por WhatsApp:** Los usuarios con cuentas de empresa con verificación de administrador activa (`verified_by_admin = true`) pueden marcar la opción "Recibir este reporte también por WhatsApp". Esto notifica al administrador mediante correo SMTP para que se lo reenvíe manualmente.
7. **Programa de Referidos por Usuario:** Cada cuenta dispone de un código de referidos único (`window.location.origin + '/?ref=CODE'`) para invitar a otros analistas y mapear la relación de referidos al momento del registro.
8. **Reporte de Errores e Incidencias:** Un botón persistente "Reportar Problema" abre un formulario para detallar problemas técnicos, capturar la URL actual y opcionalmente adjuntar capturas, guardando el registro y notificando de inmediato a los administradores por SMTP.
9. **Canal de Contacto Directo con el Creador:** Se añade un botón "Escríbeme por WhatsApp" en el pie de página de la landing pública enlazando a `https://wa.me/5351080807` para consultas generales.

---

## 9. Directorio de Dos Lados (Fundadores e Inversión) y Modelos de Persistencia
Hemos expandido DealScout AI para convertirse en un directorio de dos lados altamente estructurado, que conecta a fundadores que buscan capital o están abiertos a adquisición con inversionistas/VCs de todo el mundo. Esta característica se apoya en modelos de base de datos relacionales, flujos avanzados de verificación de cuentas y alertas SMTP automáticas:

### 1. Modelado de Base de Datos (SQLAlchemy)
El backend implementa dos tablas relacionales específicas para soportar este flujo de negocio:
- **`CompanyListing` (Tabla `company_listings`):** Almacena la propuesta pública de la startup.
  - `id` (Clave primaria).
  - `report_id` (Relación FK con la tabla `reports` para vincular el score y hallazgos).
  - `user_id` (Relación FK con la tabla `users` para identificar al fundador propietario).
  - `category` (`"investment"` o `"acquisition"`).
  - `slug` (Generado de forma única a partir del nombre corporativo para URL amigable, ej. `/empresa/stripe`).
  - `visible_name`, `visible_industry`, `visible_country`, `visible_description` (Datos proporcionados mediante el Opt-In de privacidad).
  - `show_numerical_score` (Booleano para alternar entre el score numérico o el badge cualitativo).
  - `status` (`pending_review`, `approved`, `rejected` para la moderación).
  - `expires_at` / `approved_at` (Marcas de tiempo de control de ciclo de vida).
- **`ListingInterest` (Tabla `listing_interests`):** Registra las expresiones de interés ("Me interesa") enviadas por los inversionistas.
  - `id` (Clave primaria).
  - `listing_id` (FK a `company_listings`).
  - `vc_user_id` (FK a `users` que identifica al inversionista interesado).
  - `created_at` (Timestamp de registro).

### 2. Flujo Completo de Registro y Verificación de Cuentas (Founder / VC)
Para garantizar la autenticidad en el marketplace de dos lados, implementamos dos niveles de verificación de identidad:
- **Verificación Automática de Dominio (`verified_domain`):** Al registrarse una cuenta tipo `empresa`, el sistema extrae el dominio del correo electrónico de registro (ej. `email = founder@stripe.com`) y el dominio purificado del sitio web oficial de la compañía (ej. `company_website = https://stripe.com`). Si coinciden y no pertenecen a un proveedor público común (como Gmail o Yahoo), el campo `verified_domain` se marca automáticamente como `true` en la base de datos.
- **Verificación Manual de Administrador (`verified_by_admin`):** Los administradores pueden visualizar toda la lista de usuarios mediante el endpoint `/admin/users` y activar manualmente la insignia VIP `verified_by_admin` utilizando `/admin/users/{id}/verify-by-admin` para certificar cuentas de socios clave de forma manual.

### 3. Lógica del Botón "Me interesa" y Alertas de Lead Generation
- **Restricción de Roles:** El botón "Me interesa" está estrictamente bloqueado para fundadores o dueños de su propia publicación. Solo usuarios autenticados con cuentas tipo `personal` (Inversionistas / VCs) o administradores pueden accionarlo.
- **Notificación por SMTP instantánea:** Al activarse la expresión de interés, el sistema registra el registro de interés en la base de datos para prevenir duplicados y despacha una alerta por correo SMTP automática al fundador (`founder.email`) detallando el nombre de la startup que generó interés, el nombre/firma del inversionista y su correo de contacto directo para permitir la comunicación bidireccional inmediata.

### 4. Ciclo de Vida y Proceso de Renovación de Listados
Los listados aprobados expiran automáticamente a los 60 días (ajustable mediante la variable de entorno `LISTING_EXPIRY_DAYS`).
- El planificador continuo `monitoring.py` comprueba diariamente el vencimiento.
- Antes de ocultar el listado, el sistema despacha una advertencia automatizada al correo del fundador incluyendo un enlace directo firmado que permite renovar la publicación por otros 60 días de manera inmediata y sencilla con un solo clic.

### 5. Páginas Compartibles y Badges Dinámicos SVG
- **Páginas con Metadatos Open Graph (`/empresa/{slug}`):** Se sirven páginas estáticas renderizadas en el servidor usando reemplazos controlados sobre `templates/empresa.html`, inyectando metadatos OG de Twitter y LinkedIn optimizados para que las startups compartan su perfil de readiness en redes sociales.
- **Badge en formato SVG (`/empresa/{slug}/badge`):** Genera en tiempo real un gráfico vectorial SVG impecable con el nombre, sector, país e Investor Readiness Score (o insignia cualitativa) de la startup, listo para ser incrustado en el sitio web de la compañía o repositorios de GitHub.

---

## 10. Variables de Entorno y Configuración
| Variable | Descripción | Valor por defecto |
|---|---|---|
| `LLM_PROVIDER` | Proveedor principal de LLM (`openrouter` \| `grok` \| `openai`) | `openrouter` |
| `API_KEY_OPENROUTER` | API Key para la plataforma OpenRouter | Opcional |
| `API_KEY_GROK` | API Key para la consola de desarrollador de xAI | Opcional |
| `API_KEY_OPENAI` | API Key estándar para la plataforma OpenAI | Opcional |
| `DATABASE_URL` | URL de base de datos relacional (PostgreSQL en producción) | `sqlite:///vcdiligence.db` |
| `JWT_SECRET` | Firma de seguridad para tokens JWT de sesión | Clave autogenerada |
| `ENV` | Entorno de despliegue (`production` para deshabilitar reload) | `development` |
| `SMTP_HOST` | Servidor SMTP para alertas por correo | `smtp.gmail.com` |
| `SMTP_PORT` | Puerto de conexión SMTP | `587` |
| `SMTP_USERNAME`| Cuenta/correo emisor para SMTP | Opcional |
| `SMTP_PASSWORD`| Clave de aplicación/contraseña SMTP | Opcional |
| `SMTP_FROM`    | Remitente del mensaje de correo | `noreply@dealscout.ai` |

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
