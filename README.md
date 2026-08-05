# LinkedIn MCP Server — Experimentation

**Repo:** https://github.com/stickerdaniel/linkedin-mcp-server  
**Package:** `mcp-server-linkedin` (PyPI)  
**Stack:** Python 3.12, FastMCP, Patchright (Chromium), uvx

**Canonical local checkout:** `/Users/iliyanivanov/Desktop/Signals/signal-platform`

The production signal systems are exposed as named entries in
`/Users/iliyanivanov/Desktop/Signals` while remaining inside this single Git
repository:

- `Hiring Pipeline Roles` → `signals/pipeline-engine-hiring-outreach`
- `Technology-Based Outreach` → `signals/technology-based-outreach`
- `Automation Jobs LinkedIn` → `signals/automation_jobs_linkedin`

The former `/Users/iliyanivanov/Desktop/linkedin-mcp-experimentation` path is a
temporary compatibility symlink. New commands and documentation should use the
canonical checkout above.

---

## Architecture

| Consumer | Transport | Where |
|----------|-----------|-------|
| Claude Desktop / Claude Code | stdio | Local via `uvx` |
| n8n | streamable-http | Modal (`modal_linkedin.py`) |

**Never run both simultaneously** — they share the `~/.linkedin-mcp` browser profile (local) or the Modal Volume copy.

---

## Setup

### 1. Claude Desktop (stdio)

Config is already added to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
"linkedin": {
  "command": "uvx",
  "args": ["mcp-server-linkedin@latest"],
  "env": { "UV_HTTP_TIMEOUT": "300" }
}
```

**First-time login:**
```bash
uvx mcp-server-linkedin@latest --login
```
Opens a real Chromium window. Log in manually. Session persists at `~/.linkedin-mcp/`.

**Verify:** Restart Claude Desktop, then call `get_my_profile` — should return your profile.

---

### 2. Modal (n8n HTTP transport)

**One-time bootstrap:**
```bash
# 1. Log in locally (if not done already)
uvx mcp-server-linkedin@latest --login

# 2. Create the Modal Volume
modal volume create linkedin-mcp-vol

# 3. Upload your session to Modal
modal volume put linkedin-mcp-vol ~/.linkedin-mcp /root/.linkedin-mcp

# 4. Deploy
modal deploy modal_linkedin.py
```

Modal will return a public URL like `https://iliyanivanov--linkedin-mcp-linkedin-mcp-server.modal.run`

**n8n call format:**
```
POST https://<your-modal-url>/mcp
Content-Type: application/json

{ "jsonrpc": "2.0", "method": "tools/call", "params": { "name": "search_people", "arguments": { "keywords": "..." } }, "id": 1 }
```

**Session refresh (when cookies expire, ~monthly):**
```bash
uvx mcp-server-linkedin@latest --login
modal volume put linkedin-mcp-vol ~/.linkedin-mcp /root/.linkedin-mcp
```

---

## Safety Constraints

### Hard Rules (never violate)
- `confirm_send=True` always required for `send_message`
- Max **~15 profiles per session** — call `close_session` after
- **No simultaneous** Claude stdio + Modal access
- `connect_with_person` is **off-limits** during experimentation (high risk, known bugs)

### n8n Workflow Rules
- Add **10–15 second Wait node** between every LinkedIn tool call
- Never schedule LinkedIn workflows more frequently than **once per 30 minutes**
- Never loop over lists larger than **10 items per run**
- Prefer read operations (`search_people`, `get_person_profile`) over write operations (`send_message`)
- Use `get_company_employees` sparingly — higher detection risk

### Session Hygiene
- Re-export cookies monthly or whenever auth fails
- Always call `close_session` at end of Claude sessions that used LinkedIn tools
- Keep Modal concurrency at `1` (already configured in `modal_linkedin.py`)

---

## Tool Reference (17 tools)

### Lead Research

| Tool | Key params | Risk |
|------|-----------|------|
| `search_people` | `keywords`, `location`, `network` (`F`/`S`/`O`), `current_company` (URN) | Low |
| `get_person_profile` | `linkedin_username`, `sections?` | Low |
| `get_my_profile` | `sections?` | None |
| `get_company_profile` | `company_name`, `sections?` — returns `company_urn` | Low |
| `get_company_employees` | `company_name`, `keyword_filter?` | Medium |
| `search_companies` | `keywords` | Low |
| `get_sidebar_profiles` | — | Low |

**Tip:** Get `company_urn` from `get_company_profile`, then pass to `search_people(current_company=urn)` to filter by company.

**Profile sections:** `experience`, `education`, `interests`, `honors`, `languages`, `certifications`, `skills`, `projects`, `contact_info`, `posts`  
Each section = 1 extra page navigation. Only request what you need.

### Outreach / Messaging

| Tool | Key params | Risk |
|------|-----------|------|
| `send_message` | `linkedin_username`, `message`, `confirm_send=True` | High — always explicit confirm |
| `get_inbox` | `limit` (1–50, default 20) | None |
| `get_conversation` | `linkedin_username` or `thread_id` | None |
| `search_conversations` | `keywords`, `limit` | None |
| `connect_with_person` | — | **Off-limits** |

### Content / Feed Monitoring

| Tool | Key params | Risk |
|------|-----------|------|
| `get_feed` | `num_posts` (1–50) | Low |
| `get_company_posts` | `company_name` | Low |

### Job Market Intelligence

| Tool | Key params | Risk |
|------|-----------|------|
| `search_jobs` | `keywords`, `location`, `job_type`, `experience_level`, `date_posted` | Low |
| `get_job_details` | `job_id` — get IDs from `search_jobs` | Low |

### Session

| Tool | Notes |
|------|-------|
| `close_session` | Call at end of every Claude session that used LinkedIn tools |

---

## Workflow Ideas (future)

- **Lead enrichment pipeline:** `search_people` → `get_person_profile(sections=["experience","contact_info"])` → enrich row in Google Sheet
- **Company intelligence:** `get_company_profile` + `get_company_posts` → summarize with Claude → feed into lemlist campaign
- **Job signal monitoring:** `search_jobs` daily → detect hiring patterns by role/location → trigger alerts
- **Inbox triage:** `get_inbox` → `get_conversation` for unread threads → draft reply suggestions with Claude

## Shared pipeline lead sheet

Working signal collectors append qualified findings to:

`signals/exports/pipeline_leads.csv`

Use the `signal_type` column to route leads into downstream pipelines. Duplicate
rows are blocked by `signal_type + lead_key`; person keys use LinkedIn profile
URLs and company keys use domains or company names.

See `working-signals.md` for the current production and future-signal status.
