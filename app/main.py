from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import get_pool, close_pool
from app.logging_config import setup_logging
from app.webhooks import router as webhooks_router
from app.stats import router as stats_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    import sys
    print("LIFESPAN: setting up logging…", flush=True, file=sys.stderr)
    setup_logging(settings.log_level)
    print("LIFESPAN: pre-initializing repository…", flush=True, file=sys.stderr)
    from app.repository import LeadRepository
    try:
        await LeadRepository.get_instance()
        print("LIFESPAN: repository ready.", flush=True, file=sys.stderr)
    except Exception as e:
        print(f"LIFESPAN: WARNING — repository fallback: {e}", flush=True, file=sys.stderr)

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from app.pipeline import set_checkpointer
    async with AsyncSqliteSaver.from_conn_string("checkpoints.sqlite") as checkpointer:
        set_checkpointer(checkpointer)
        print("LIFESPAN: checkpoint saver ready.", flush=True, file=sys.stderr)
        yield
    
    print("LIFESPAN: shutting down…", flush=True, file=sys.stderr)
    await close_pool()
    print("LIFESPAN: shutdown complete", flush=True, file=sys.stderr)


app = FastAPI(title="Speed-to-Lead AI Router", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks_router)
app.include_router(stats_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def demo_form():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="dark">
<title>Speed-to-Lead — AI Lead Router</title>
<meta name="description" content="AI-powered lead enrichment, scoring, and routing pipeline. Submit a lead and watch it flow through the system in under 10 seconds.">
<meta name="theme-color" content="#0B1120">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=DM+Sans:ital,wght@0,400;0,500;0,600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
/* ============================================================
   DESIGN TOKENS
   ============================================================ */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  /* palette — navy base, amber signal, status colors */
  --bg:          #0B1120;
  --bg-raised:   #111827;
  --surface:     #1A2335;
  --surface-2:   #222D42;
  --border:      #2A3650;
  --border-focus:#E5A93E;

  --text:        #E2E8F0;
  --text-muted:  #7B8BA5;
  --text-dim:    #4A5568;

  --amber:       #E5A93E;
  --amber-dim:   rgba(229,169,62,.12);
  --coral:       #F0614A;
  --teal:        #2DD4A8;
  --lavender:    #A78BFA;
  --blue:        #60A5FA;

  /* type */
  --font-display: 'Space Grotesk', system-ui, sans-serif;
  --font-body:    'DM Sans', system-ui, sans-serif;
  --font-mono:    'JetBrains Mono', 'Fira Code', monospace;

  /* spacing */
  --radius-sm: 6px;
  --radius:    10px;
  --radius-lg: 14px;

  --ease: cubic-bezier(.4, 0, .2, 1);
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}

html { scroll-behavior: smooth; }

body {
  font-family: var(--font-body);
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* ============================================================
   SKIP LINK
   ============================================================ */
.skip-link {
  position: absolute;
  top: -100%;
  left: 1rem;
  background: var(--amber);
  color: var(--bg);
  padding: .5rem 1rem;
  border-radius: var(--radius-sm);
  font-weight: 600;
  z-index: 100;
  text-decoration: none;
}
.skip-link:focus { top: 1rem; }

/* ============================================================
   HEADER
   ============================================================ */
.site-header {
  padding: 3.5rem 1.5rem 1rem;
  text-align: center;
  position: relative;
}
.site-header::before {
  content: '';
  position: absolute;
  top: -40%;
  left: 20%;
  width: 60%;
  height: 100%;
  background: radial-gradient(ellipse at center, rgba(229,169,62,.08) 0%, transparent 70%);
  pointer-events: none;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: .6rem;
  margin-bottom: .5rem;
}
.brand-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--amber);
  box-shadow: 0 0 12px rgba(229,169,62,.5);
  animation: dot-pulse 2.4s ease-in-out infinite;
}
@keyframes dot-pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 12px rgba(229,169,62,.5); }
  50% { opacity: .5; box-shadow: 0 0 4px rgba(229,169,62,.2); }
}
.brand h1 {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: clamp(1.6rem, 4vw, 2.2rem);
  color: var(--text);
  letter-spacing: -.02em;
  text-wrap: balance;
}
.brand h1 span {
  color: var(--amber);
}

.site-header p {
  color: var(--text-muted);
  max-width: 480px;
  margin: 0 auto;
  font-size: .92rem;
}

/* ============================================================
   LAYOUT
   ============================================================ */
main {
  max-width: 1040px;
  margin: 0 auto;
  padding: 1.5rem 1.5rem 4rem;
  display: grid;
  grid-template-columns: 7fr 5fr;
  gap: 1.5rem;
  align-items: start;
}
@media (max-width: 780px) {
  main { grid-template-columns: 1fr; }
}

/* ============================================================
   CARDS
   ============================================================ */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 1.75rem;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
}
.card-title {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 1rem;
  letter-spacing: -.01em;
}

/* ============================================================
   PIPELINE TRACE (signature element)
   ============================================================ */
.trace {
  display: flex;
  align-items: center;
  gap: 0;
  margin-bottom: 1.5rem;
  padding: .75rem 0;
}
.trace-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: .35rem;
  flex-shrink: 0;
  position: relative;
}
.trace-ring {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 2px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: .7rem;
  color: var(--text-dim);
  background: var(--bg-raised);
  transition: border-color .4s var(--ease), color .4s var(--ease), background .4s var(--ease), box-shadow .4s var(--ease);
}
.trace-label {
  font-family: var(--font-mono);
  font-size: .6rem;
  font-weight: 500;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: .06em;
  transition: color .4s var(--ease);
}
.trace-wire {
  flex: 1;
  height: 2px;
  background: var(--border);
  position: relative;
  overflow: hidden;
  min-width: 24px;
}
.trace-wire::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, var(--amber), transparent);
  transform: translateX(-100%);
  transition: none;
}

/* trace states */
.trace-node.active .trace-ring {
  border-color: var(--amber);
  color: var(--amber);
  box-shadow: 0 0 16px rgba(229,169,62,.25);
}
.trace-node.active .trace-label { color: var(--amber); }

.trace-node.done .trace-ring {
  border-color: var(--teal);
  color: var(--teal);
  background: rgba(45,212,168,.08);
}
.trace-node.done .trace-label { color: var(--teal); }

.trace-wire.lit::after {
  animation: wire-flow .6s var(--ease) forwards;
}
@keyframes wire-flow {
  to { transform: translateX(100%); }
}

/* ============================================================
   FORM
   ============================================================ */
.field { margin-bottom: 1.1rem; }
.field label {
  display: block;
  font-size: .75rem;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: .35rem;
  letter-spacing: .02em;
}
.field label .req {
  color: var(--coral);
  margin-left: .15rem;
}

.field input,
.field textarea {
  width: 100%;
  background: var(--bg-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: .65rem .85rem;
  color: var(--text);
  font-family: var(--font-body);
  font-size: .88rem;
  outline: none;
  transition: border-color .2s var(--ease), box-shadow .2s var(--ease);
}
.field input:focus-visible,
.field textarea:focus-visible {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px var(--amber-dim);
}
.field input::placeholder,
.field textarea::placeholder {
  color: var(--text-dim);
}
.field textarea { resize: vertical; min-height: 72px; }

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}
@media (max-width: 500px) {
  .form-row { grid-template-columns: 1fr; }
}

/* ============================================================
   SUBMIT BUTTON
   ============================================================ */
.submit-btn {
  width: 100%;
  padding: .75rem;
  border: none;
  border-radius: var(--radius);
  background: var(--amber);
  color: var(--bg);
  font-family: var(--font-display);
  font-size: .9rem;
  font-weight: 700;
  letter-spacing: -.01em;
  cursor: pointer;
  transition: transform .15s var(--ease), box-shadow .15s var(--ease), opacity .15s;
  position: relative;
  touch-action: manipulation;
  -webkit-tap-highlight-color: transparent;
}
.submit-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 20px rgba(229,169,62,.3);
}
.submit-btn:active { transform: translateY(0); }
.submit-btn:focus-visible {
  outline: 2px solid var(--amber);
  outline-offset: 2px;
}
.submit-btn:disabled {
  opacity: .45;
  cursor: not-allowed;
  transform: none;
}
.submit-btn .spinner {
  display: none;
  width: 16px; height: 16px;
  border: 2px solid transparent;
  border-top-color: var(--bg);
  border-radius: 50%;
  animation: spin .6s linear infinite;
  margin: 0 auto;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ============================================================
   RESULT BANNER
   ============================================================ */
.result-banner {
  margin-top: 1rem;
  padding: .7rem .9rem;
  border-radius: var(--radius);
  font-size: .82rem;
  display: none;
  animation: slide-up .25s var(--ease);
}
@keyframes slide-up {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}
.result-banner.success {
  display: block;
  background: rgba(45,212,168,.08);
  border: 1px solid var(--teal);
  color: var(--teal);
}
.result-banner.duplicate {
  display: block;
  background: rgba(229,169,62,.08);
  border: 1px solid var(--amber);
  color: var(--amber);
}
.result-banner.error {
  display: block;
  background: rgba(240,97,74,.08);
  border: 1px solid var(--coral);
  color: var(--coral);
}

/* ============================================================
   STATS PANEL
   ============================================================ */
.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: .6rem;
  margin-bottom: 1.25rem;
}
.stat-cell {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: .85rem .75rem;
  text-align: center;
  transition: border-color .2s var(--ease);
}
.stat-cell:hover { border-color: var(--border-focus); }
.stat-value {
  font-family: var(--font-mono);
  font-size: 1.35rem;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.stat-label {
  font-size: .65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .05em;
  color: var(--text-muted);
  margin-top: .2rem;
}
.stat-cell.hot     .stat-value { color: var(--coral); }
.stat-cell.warm    .stat-value { color: var(--amber); }
.stat-cell.cold    .stat-value { color: var(--blue); }
.stat-cell.review  .stat-value { color: var(--lavender); }
.stat-cell.total   .stat-value { color: var(--text); }
.stat-cell.full-width { grid-column: 1 / -1; }

.divider {
  height: 1px;
  background: var(--border);
  margin: .5rem 0;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: .55rem 0;
  font-size: .82rem;
}
.meta-key { color: var(--text-muted); }
.meta-val {
  font-family: var(--font-mono);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.meta-val.danger { color: var(--coral); }

/* Refresh button */
.refresh-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-muted);
  padding: .3rem .65rem;
  border-radius: var(--radius-sm);
  font-family: var(--font-body);
  font-size: .72rem;
  font-weight: 600;
  cursor: pointer;
  transition: color .2s var(--ease), border-color .2s var(--ease);
  touch-action: manipulation;
  -webkit-tap-highlight-color: transparent;
}
.refresh-btn:hover { color: var(--amber); border-color: var(--amber); }
.refresh-btn:focus-visible {
  outline: 2px solid var(--amber);
  outline-offset: 2px;
}

/* loading skeleton */
.loading {
  animation: skeleton-pulse 1.8s ease-in-out infinite;
}
@keyframes skeleton-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .3; }
}

/* ============================================================
   FOOTER
   ============================================================ */
.site-footer {
  text-align: center;
  padding: 1.5rem;
  color: var(--text-dim);
  font-size: .72rem;
  border-top: 1px solid var(--border);
  max-width: 1040px;
  margin: 0 auto;
}
.site-footer a {
  color: var(--text-muted);
  text-decoration: none;
}
.site-footer a:hover { color: var(--amber); }
</style>
</head>
<body>

<a class="skip-link" href="#main-content">Skip to main content</a>

<header class="site-header">
  <div class="brand">
    <div class="brand-dot" aria-hidden="true"></div>
    <h1>Speed-to-<span>Lead</span></h1>
  </div>
  <p>Submit a lead and watch it flow through enrichment, scoring, and routing in under 10 seconds.</p>
</header>

<main id="main-content">
  <!-- LEFT: Lead capture -->
  <div class="card" id="formCard">
    <div class="card-header">
      <h2 class="card-title">New lead</h2>
    </div>

    <!-- Pipeline trace -->
    <div class="trace" id="trace" role="status" aria-live="polite" aria-label="Pipeline progress">
      <div class="trace-node" id="tn-submit">
        <div class="trace-ring">1</div>
        <span class="trace-label">Ingest</span>
      </div>
      <div class="trace-wire" id="tw-1"></div>
      <div class="trace-node" id="tn-enrich">
        <div class="trace-ring">2</div>
        <span class="trace-label">Enrich</span>
      </div>
      <div class="trace-wire" id="tw-2"></div>
      <div class="trace-node" id="tn-score">
        <div class="trace-ring">3</div>
        <span class="trace-label">Score</span>
      </div>
      <div class="trace-wire" id="tw-3"></div>
      <div class="trace-node" id="tn-route">
        <div class="trace-ring">4</div>
        <span class="trace-label">Route</span>
      </div>
    </div>

    <form id="leadForm" autocomplete="off">
      <div class="form-row">
        <div class="field">
          <label for="name">Name <span class="req" aria-label="required">*</span></label>
          <input id="name" name="name" type="text" placeholder="Jane Smith" required autocomplete="name" spellcheck="false">
        </div>
        <div class="field">
          <label for="email">Email <span class="req" aria-label="required">*</span></label>
          <input id="email" name="email" type="email" placeholder="jane@company.com" required autocomplete="email" spellcheck="false">
        </div>
      </div>
      <div class="form-row">
        <div class="field">
          <label for="phone">Phone</label>
          <input id="phone" name="phone" type="tel" placeholder="+1 (555) 123-4567" autocomplete="tel" inputmode="tel">
        </div>
        <div class="field">
          <label for="company_domain">Company domain</label>
          <input id="company_domain" name="company_domain" type="text" placeholder="company.com" spellcheck="false">
        </div>
      </div>
      <div class="field">
        <label for="message">Message</label>
        <textarea id="message" name="message" placeholder="Tell us about your needs…"></textarea>
      </div>
      <input type="hidden" name="source" value="demo_form">
      <button class="submit-btn" type="submit" id="submitBtn">
        <span class="btn-text">Send lead</span>
        <span class="spinner" aria-hidden="true"></span>
      </button>
    </form>
    <div class="result-banner" id="result" role="alert" aria-live="assertive"></div>
  </div>

  <!-- RIGHT: Stats -->
  <div class="card" id="statsCard">
    <div class="card-header">
      <h2 class="card-title">Pipeline stats</h2>
      <button class="refresh-btn" id="refreshBtn" type="button" aria-label="Refresh stats">Refresh</button>
    </div>

    <div class="stats-grid" id="statsGrid">
      <div class="stat-cell total full-width">
        <div class="stat-value loading" id="stat-total">0</div>
        <div class="stat-label">Total leads</div>
      </div>
      <div class="stat-cell hot">
        <div class="stat-value" id="stat-routed">0</div>
        <div class="stat-label">Hot</div>
      </div>
      <div class="stat-cell warm">
        <div class="stat-value" id="stat-nurture">0</div>
        <div class="stat-label">Warm</div>
      </div>
      <div class="stat-cell cold">
        <div class="stat-value" id="stat-cold">0</div>
        <div class="stat-label">Cold</div>
      </div>
      <div class="stat-cell review">
        <div class="stat-value" id="stat-review">0</div>
        <div class="stat-label">Review</div>
      </div>
    </div>

    <div class="divider"></div>

    <div id="metaStats">
      <div class="meta-row">
        <span class="meta-key">Avg latency</span>
        <span class="meta-val" id="meta-latency">&mdash;</span>
      </div>
      <div class="meta-row">
        <span class="meta-key">Alert failures</span>
        <span class="meta-val danger" id="meta-failed">0</span>
      </div>
      <div class="meta-row">
        <span class="meta-key">Oldest unresolved</span>
        <span class="meta-val" id="meta-oldest">None</span>
      </div>
    </div>
  </div>
</main>

<footer class="site-footer">
  Built by <a href="https://github.com/NoumanZahid-85" target="_blank" rel="noopener noreferrer" translate="no">Nouman Zahid</a> &middot; FastAPI + LangGraph + Neon
</footer>

<script>
  const form    = document.getElementById('leadForm');
  const result  = document.getElementById('result');
  const btn     = document.getElementById('submitBtn');
  const btnText = btn.querySelector('.btn-text');
  const spinner = btn.querySelector('.spinner');

  const nodes = ['tn-submit','tn-enrich','tn-score','tn-route'];
  const wires = ['tw-1','tw-2','tw-3'];

  function resetTrace() {
    nodes.forEach(id => {
      const el = document.getElementById(id);
      el.classList.remove('active','done');
    });
    wires.forEach(id => {
      const el = document.getElementById(id);
      el.classList.remove('lit');
    });
  }

  function advanceTrace(step) {
    const idx = nodes.indexOf(step);
    nodes.forEach((id, i) => {
      const el = document.getElementById(id);
      el.classList.remove('active','done');
      if (i < idx) el.classList.add('done');
      else if (i === idx) el.classList.add('active');
    });
    wires.forEach((id, i) => {
      const el = document.getElementById(id);
      if (i < idx) {
        el.classList.add('lit');
      }
    });
  }

  function completeTrace() {
    nodes.forEach(id => {
      const el = document.getElementById(id);
      el.classList.remove('active');
      el.classList.add('done');
    });
    wires.forEach(id => {
      document.getElementById(id).classList.add('lit');
    });
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    result.className = 'result-banner';
    result.style.display = 'none';
    btn.disabled = true;
    btnText.style.display = 'none';
    spinner.style.display = 'block';
    resetTrace();
    advanceTrace('tn-submit');

    const body = Object.fromEntries(new FormData(form));
    for (const key of ['phone','company_domain','message']) {
      if (!body[key]) delete body[key];
    }

    try {
      advanceTrace('tn-enrich');
      const res = await fetch('/webhook/lead', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();

      if (!res.ok) {
        result.textContent = data.detail ? JSON.stringify(data.detail) : 'Validation failed. Check your inputs.';
        result.className = 'result-banner error';
      } else if (data.status === 'duplicate_ignored') {
        result.textContent = 'This lead was already submitted.';
        result.className = 'result-banner duplicate';
      } else {
        result.textContent = 'Lead accepted (ID ' + data.id + ') — pipeline running.';
        result.className = 'result-banner success';
        setTimeout(() => advanceTrace('tn-score'), 2200);
        setTimeout(() => advanceTrace('tn-route'), 4400);
        setTimeout(() => { completeTrace(); loadStats(); }, 6500);
      }
    } catch (err) {
      result.textContent = 'Could not reach the server. ' + err.message;
      result.className = 'result-banner error';
    } finally {
      btn.disabled = false;
      btnText.style.display = 'inline';
      spinner.style.display = 'none';
    }
  });

  async function loadStats() {
    try {
      const res = await fetch('/stats');
      const data = await res.json();
      const s = data.by_status || {};
      document.getElementById('stat-total').textContent   = data.total_leads ?? 0;
      document.getElementById('stat-routed').textContent   = s.routed ?? 0;
      document.getElementById('stat-nurture').textContent  = s.nurture ?? 0;
      document.getElementById('stat-cold').textContent     = s.cold ?? 0;
      document.getElementById('stat-review').textContent   = (s.needs_review ?? 0) + (s.alert_failed ?? 0);
      document.getElementById('meta-latency').textContent  = data.avg_elapsed_seconds
        ? data.avg_elapsed_seconds.toFixed(2) + 's'
        : '\\u2014';
      document.getElementById('meta-failed').textContent   = s.alert_failed ?? 0;
      const oldest = data.oldest_unresolved;
      document.getElementById('meta-oldest').textContent   = oldest ? oldest.created_at : 'None';
      document.getElementById('stat-total').classList.remove('loading');
    } catch (err) {
      console.error('Stats load failed:', err);
    }
  }

  document.getElementById('refreshBtn').addEventListener('click', loadStats);
  loadStats();
</script>
</body>
</html>"""
