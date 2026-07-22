# DealScout AI — VC Due Diligence Agent

An autonomous venture capital due diligence agent network that analyzes startups from public URLs, performing market sizing, competitor mapping, team profiles, metrics estimation, and generating investment reports with a deal risk score (0-100).

---

## Comprehensive Project Explanation

For a complete architectural breakdown, workflow details, multi-provider configuration, scraping engine, and installation step-by-step, **please refer to our master documentation**:

👉 **[EXPLICACION_PROYECTO.md](EXPLICACION_PROYECTO.md)**

---

## Core Features

- **Autonomous Agent Network:** Coordinated team of 5 specialized CrewAI investment agents.
- **Smart API-keyless Scraper:** Direct crawl & DuckDuckGo search integration requiring zero expensive subscription keys.
- **Multi-Provider LLM Abstraction:** Seamlessly switch between OpenRouter, Grok, and OpenAI with automated fallback systems.
- **iOS Glassmorphism Interface:** Ultra-modern dark-themed responsive frontend with circular deal score dials and tabbed memo panels.
- **Instant Demo Mode:** Immediate zero-cost testing using cached startup data for `stripe.com` and `vcdiligence.com`.
- **Render Ready:** Pre-configured for deployment on Render's Free tier with a background keep-alive ping loop.

---

## Quick Start (Local Run)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/SURESHBEEKHANI/CrewAI-End-to-End.git DealScoutAI
   cd DealScoutAI
   ```

2. **Setup virtual environment and install package:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

3. **Configure Environment:**
   ```bash
   cp .env.example .env
   ```

4. **Launch Application:**
   ```bash
   vcdiligence
   ```
   Open `http://localhost:10000` in your web browser.
