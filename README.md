# DealScout AI — Multi-Agent Venture Capital Due Diligence & Investment Directory

nota importante : solo necesita una sola api de ai para funcionar mas adelante se le describe los modelos que se pueden utilizar 
el sistema esta echo tanto para funcionar a bajo consumo desde un por ejemplo render gratuito manteniendo un rendimiento estable y seguro , como para correr en algo mas potencia el cambio de potencia lo hace significativamente veloz y esta adaptado para adaptar e a entornos y dificultades trabaja bien con poco recursos 

DealScout AI (configured as `VCDueDiligenceAgent`) is an autonomous, enterprise-grade Venture Capital due diligence engine and interactive dual-sided marketplace. Powered by **FastAPI**, **SQLAlchemy**, and **CrewAI**, it automates the process of analyzing startups from public URLs, Pitch Decks (PDF/PPTX), or LinkedIn profiles. It acts as a comprehensive decision-support system, generating detailed white-label investment reports, readiness scores (0-100), and a secure directory to match founders with qualified buyers and investors.

---

## 🌟 Core Features

- **Autonomous Multi-Agent Cognition:** Coordinated team of 6 specialized CrewAI agents that research, analyze, debate, and compile the final investment memo.
- **Dual-Sided Marketplace Directory:** Connecting Founders (seeking investment or open to acquisition) and Buyers/Investors (VCs, independent angels, and corporate development analysts) securely.
- **Adaptive Scraper (Playwright fallback):** A robust scraping engine combining fast `requests/BS4` extraction with a lazy-loaded dynamic **Playwright headless Chromium** browser to easily bypass modern SPA rendering.
- **Live External API Integration:** Hits real, production-ready databases in real time to fetch corporate records (OpenCorporates, SEC EDGAR Form D), patents (USPTO), legal litigation history (CourtListener), and tech activity (GitHub API).
- **White-Label Customization:** Complete customizable interface, allowing administrators to configure custom company names and upload high-resolution organization logos dynamically rendered inside modern ReportLab PDF reports.
- **Continuous Monitoring:** Periodic automated scanning (using APScheduler) to track score changes, legal hazards, and technical updates over time.
- **Privacy-First Testimonial Engine:** Feedback submissions with explicit opt-in preferences for comment sharing, profile photos, and name displays. Testimonials with screenshot attachments require manual administrator approval.
- **SSRF Mitigations & Rate-Limiting:** Production-ready protection policies verifying IP addresses to prevent Server-Side Request Forgery and rate limits on start analysis requests.

---

## 🛠 Directory and Account Types ("Buyer vs Founder")

The platform separates accounts and interactions into distinct, secure flows:

### 1. Account Types
- **Personal / Investor Accounts:** For venture analysts, angels, and buyers. They can run analyses, register investment decisions, use decision calibration, explore the listing directory, and express interest in companies.
- **Empresa / Founder Accounts:** For startup founders and company executives. They can analyze their company, opt-in to list their company publicly, and manage their listings.
- **Domain Verification:** If a founder signs up with an enterprise email matching their confirmed company website (e.g. `founder@stripe.com` and `stripe.com`), their account is automatically marked as `verified_domain = true`.
- **Manual Verification:** Administrators can manually toggle VIP company accounts with `verified_by_admin = true`.

### 2. Dual-Sided Directory Flow ("Me interesa")
- **Founder Opt-In:** Startups are **never** published automatically. Founders must fill out an explicit form selecting their category ("investment" or "acquisition"), public visibility description, and decide whether to show their numerical score or a qualitative badge ("Excelente potencial", "Alto potencial").
- **Admin Moderation:** New listings enter a `pending_review` state and must be manually approved by an admin.
- **Lead Generation ("Me interesa"):** The founder's contact email is completely hidden. Authenticated VC/buyer accounts can click "Me interesa" to submit an expression of interest. This records the action in `listing_interests` and dispatches an automated SMTP notification email directly to the founder with the VC's contact info.
- **Listing Expiry:** Listings automatically expire and hide after a configurable period (default 60 days). The system alerts the founder via email prior to expiration with a one-click renew link.

---

## ⚙️ Environment Variables and Configuration

Configure your environment by duplicating `.env.example` to `.env`. Below is the complete specification:

| Variable | Description | Default Value / Option |
|---|---|---|
| `LLM_PROVIDER` | Main LLM provider engine | `openrouter` \| `grok` \| `openai is optional onli need one api ai no more ` |
| `API_KEY_OPENROUTER` | API credential for OpenRouter | Optional |
| `MODEL_OPENROUTER` | Selected model on OpenRouter platform | `meta-llama/llama-3.3-70b-instruct` |
| `API_KEY_GROK` | API credential for xAI Grok Console | Optional |
| `MODEL_GROK` | Selected Grok model | `grok-2-1212` |
| `API_KEY_OPENAI` | API credential for OpenAI | Optional |
| `MODEL_OPENAI` | Selected OpenAI model | `gpt-4o-mini` |
| `DATABASE_URL` | Relational database connection string | `sqlite:///vcdiligence.db` (dev fallback) |
| `PORT` | Web server port number | `10000` |
| `JWT_SECRET` | Mandatory JWT signing key. Code fails on start if empty. | Must be set |
| `MIN_USERS_TO_SHOW_STATS` | Minimum user accounts before public landing stats are active | `20` (Shows validation banner if below) |
| `LISTING_EXPIRY_DAYS` | Number of days a marketplace listing remains active | `60` |
| `SMTP_HOST` | Outgoing SMTP mail server | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USERNAME` | Outgoing SMTP email user | Optional |
| `SMTP_PASSWORD` | Outgoing SMTP email app password | Optional |
| `SMTP_FROM` | Sender display email header | `noreply@dealscout.ai` |
| `SLACK_WEBHOOK_URL` | Slack webhook URL for slack alerts | Optional |

---

## 🧩 Directory Map and Repository Layout

- `vcdiligence/app.py`: Core FastAPI application containing all router endpoints, JWT session validation, directory models interaction, administrative moderation, and template rendering.
- `vcdiligence/database.py`: SQLAlchemy database models representing Organizations, Users, Testimonials, Error Reports, Reports, Tasks, Audit Logs, and Company Listings.
- `vcdiligence/crew.py`: CrewAI agent definitions and task orchestration. Injects live-scraped text data and external public API payloads.
- `vcdiligence/scraper.py`: Advanced `SmartScraper` managing requests/BS4 extraction, lazy-loaded Playwright fallback browser, and PDF/PPTX Pitch Deck parsing.
- `vcdiligence/public_apis.py`: Independent live connectors for SEC EDGAR, CourtListener, USPTO, and the GitHub API. Includes force refresh bypass parameters.
- `vcdiligence/pdf_generator.py`: Generates beautiful, white-label, multi-page ReportLab PDF reports incorporating custom logos.
- `vcdiligence/tasks.py`: Implements background task execution via `FastAPI BackgroundTasks`.
- `vcdiligence/monitoring.py`: Periodic scheduler utilizing APScheduler to run background monitoring and renew warnings.
- `vcdiligence/validator.py`: Mitigates Server-Side Request Forgery (SSRF) and implements rate-limiting.
- `vcdiligence/seed.py`: Seed CLI to bootstrap the database with dummy analysts, admins, and pre-cached organizations.
- `vcdiligence/benchmark.py`: Admin CLI benchmarking script to run evaluations against a local gold dataset.

---

## 🚀 Quick Start & Installation

### 1. Clone the repository and install dependencies
Make sure you have [Poetry](https://python-poetry.org/) or standard python virtual environment installed.
```bash
git clone https://github.com/SURESHBEEKHANI/CrewAI-End-to-End.git DealScoutAI
cd DealScoutAI
python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

### 2. Configure Environment Variables
Create your local `.env` configuration file:
```bash
cp .env.example .env
```
Ensure you provide a secure string for `JWT_SECRET` and add your chosen `API_KEY_*`.

### 3. Bootstrap and Seed the Database
Initialize tables and populate with default credentials (admin and analyst accounts):
```bash
python -m vcdiligence.seed
```

### 4. Start the Server
Launch the local development web server:
```bash
vcdiligence
```
Open `http://localhost:10000` on your web browser.

* **Analyst Login:** `analyst@dealscout.ai` / `analystpassword`
* **Admin Login:** `admin@dealscout.ai` / `adminpassword`

---

## 🧪 Testing

To execute the unit and integration test suite and ensure no regressions exist across the routing, scrapers, or database models:
```bash
poetry run python -m unittest discover -s tests
```
## ⚡ Resource Optimization

The system is designed to be **efficient and lightweight** in production:

- **Single LLM**: The system uses **only one** LLM provider configurable via `LLM_PROVIDER` (OpenRouter, Grok, or OpenAI). It does not run multiple models simultaneously, simplifying costs and maintenance.

- **Playwright on-demand**: The smart scraper first attempts with `requests/BS4` (fast and no overhead). **Only** if it detects Cloudflare, heavy JavaScript, or SPAs, it activates Playwright headless. Once scraping is complete, the browser **automatically shuts down** to free resources.

- **SMTP as internal function**: The email service is not a standalone server. It runs **as a function within the code** that activates **only when needed** (notifications, expiration alerts, contacts). After sending the email, the connection closes.

- **Automatic database**: In environments like Render, the database (PostgreSQL) is automatically provisioned via `DATABASE_URL`. In development, it defaults to SQLite with no additional configuration.

This **on-demand** approach allows deploying the application in the cloud with optimized costs and no unnecessary background services running.
---
## 👨‍💻 Creador

**DealScout AI** es un proyecto creado y mantenido por **[Marlon Baez Mendez](https://github.com/athenacoree/MARLON-BAEZ-MENDEZ-)**.

Para más información sobre el autor, consulta su [bibliografía oficial](https://github.com/athenacoree/MARLON-BAEZ-MENDEZ-).
*For detailed instructions on architectural layers and multi-provider cognitive configurations, please check [EXPLICACION_PROYECTO.md](EXPLICACION_PROYECTO.md).*
