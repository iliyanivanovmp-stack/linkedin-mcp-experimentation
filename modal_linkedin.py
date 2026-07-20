"""
LinkedIn MCP Server on Modal

Deploys mcp-server-linkedin HTTP transport to Modal so n8n can call it remotely.
Auth cookies are persisted in Modal Volume 'linkedin-mcp-vol'.

n8n calls: POST https://<app>.modal.run/mcp (MCP JSON-RPC)

Safety: concurrency_limit=1 ensures only one browser session at a time.

──────────────────────────────────────────────────────────────────────────────
BOOTSTRAP (one-time, run on your Mac):

  1. uvx mcp-server-linkedin@latest --login
       Opens Chromium. Log in to LinkedIn manually.
       Session is saved to ~/.linkedin-mcp/

  2. modal volume create linkedin-mcp-vol

  3. Upload only the session files (NOT patchright-browsers — browser is in the image):
       modal volume put linkedin-mcp-vol ~/.linkedin-mcp/cookies.json /cookies.json
       modal volume put linkedin-mcp-vol ~/.linkedin-mcp/source-state.json /source-state.json
       modal volume put linkedin-mcp-vol ~/.linkedin-mcp/browser-install.json /browser-install.json
       modal volume put linkedin-mcp-vol ~/.linkedin-mcp/profile /profile

  4. modal deploy modal_linkedin.py

SESSION REFRESH (when cookies expire, ~monthly):
  Re-run step 1, then upload only the cookies file:
    modal volume put linkedin-mcp-vol ~/.linkedin-mcp/cookies.json /cookies.json
  Then redeploy.

SAFETY RULES:
  - Never run this server and the local stdio server simultaneously
    (both share the same ~/.linkedin-mcp browser profile when local,
     Modal reads from the volume copy)
  - Add 10-15s Wait nodes between LinkedIn calls in n8n
  - Max ~15 profiles per n8n workflow run
  - Always pass confirm_send=True for send_message
  - No connect_with_person during experimentation
──────────────────────────────────────────────────────────────────────────────
"""

import modal

app = modal.App("linkedin-mcp")

# Persistent volume for LinkedIn session cookies and browser profile
vol = modal.Volume.from_name("linkedin-mcp-vol", create_if_missing=True)

# Patchright Chromium is baked into the image (Linux x86_64 binaries) so the
# volume only needs to carry session cookies — no browser upload required.
BROWSERS_PATH = "/patchright-browsers"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install(
        # Chromium runtime dependencies
        "libnss3",
        "libnspr4",
        "libatk1.0-0",
        "libatk-bridge2.0-0",
        "libcups2",
        "libdrm2",
        "libdbus-1-3",
        "libxkbcommon0",
        "libxcomposite1",
        "libxdamage1",
        "libxfixes3",
        "libxrandr2",
        "libgbm1",
        "libasound2",
        "libpango-1.0-0",
        "libcairo2",
    )
    .pip_install("uv")
    .run_commands("uv tool install mcp-server-linkedin")
    .run_commands(
        r"""python - <<'PY'
from pathlib import Path

tool_root = Path("/root/.local/share/uv/tools/mcp-server-linkedin/lib")
matches = list(tool_root.glob("python*/site-packages/linkedin_mcp_server/scraping/extractor.py"))
if not matches:
    raise SystemExit("Could not find linkedin_mcp_server scraping extractor")

path = matches[0]
source = path.read_text()

anchor = "    async def search_jobs(\n"
if "_search_jobs_guest_api" not in source:
    helper = r'''
    async def _search_jobs_guest_api(
        self,
        keywords: str,
        location: str | None = None,
        max_pages: int = 3,
        date_posted: str | None = None,
        job_type: str | None = None,
        experience_level: str | None = None,
        work_type: str | None = None,
        easy_apply: bool = False,
        sort_by: str | None = None,
    ) -> dict[str, Any]:
        # Fallback for headless Chromium redirect loops on /jobs/search/.
        import html
        import urllib.parse
        import urllib.request

        def fetch_page(start: int) -> tuple[str, str]:
            params: dict[str, str] = {
                "keywords": keywords,
                "start": str(start),
            }
            if location:
                params["location"] = location
            if date_posted:
                params["f_TPR"] = _DATE_POSTED_MAP.get(date_posted.strip(), date_posted)
            if job_type:
                params["f_JT"] = _normalize_csv(job_type, _JOB_TYPE_MAP)
            if experience_level:
                params["f_E"] = _normalize_csv(experience_level, _EXPERIENCE_LEVEL_MAP)
            if work_type:
                params["f_WT"] = _normalize_csv(work_type, _WORK_TYPE_MAP)
            if easy_apply:
                params["f_EA"] = "true"
            if sort_by:
                params["sortBy"] = _SORT_BY_MAP.get(sort_by.strip(), sort_by)

            url = (
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
                + urllib.parse.urlencode(params)
            )
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                return url, response.read().decode("utf-8", "ignore")

        seen_ids: set[str] = set()
        job_ids: list[str] = []
        page_texts: list[str] = []
        first_url = ""

        for page_num in range(max_pages):
            start = page_num * _PAGE_SIZE
            url, body = await asyncio.to_thread(fetch_page, start)
            if not first_url:
                first_url = url
            if not body.strip():
                break

            page_ids: list[str] = []
            for match in re.finditer(r"(?:urn:li:jobPosting:|/jobs/view/)(\d+)", body):
                job_id = match.group(1)
                if job_id not in seen_ids:
                    seen_ids.add(job_id)
                    page_ids.append(job_id)
            if not page_ids:
                break
            job_ids.extend(page_ids)

            text = html.unescape(re.sub(r"<[^>]+>", " ", body))
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                page_texts.append(text)

            if len(page_ids) < _PAGE_SIZE:
                break

        result: dict[str, Any] = {
            "url": first_url or self._build_job_search_url(
                keywords,
                location=location,
                date_posted=date_posted,
                job_type=job_type,
                experience_level=experience_level,
                work_type=work_type,
                easy_apply=easy_apply,
                sort_by=sort_by,
            ),
            "sections": {"search_results": "\n---\n".join(page_texts)} if page_texts else {},
            "job_ids": job_ids,
            "source": "linkedin_jobs_guest_api",
        }
        return result

'''
    source = source.replace(anchor, helper + "\n" + anchor)

old = '''        base_url = self._build_job_search_url(
            keywords,
            location=location,
            date_posted=date_posted,
            job_type=job_type,
            experience_level=experience_level,
            work_type=work_type,
            easy_apply=easy_apply,
            sort_by=sort_by,
        )
'''
new = '''        try:
            guest_result = await self._search_jobs_guest_api(
                keywords,
                location=location,
                max_pages=max_pages,
                date_posted=date_posted,
                job_type=job_type,
                experience_level=experience_level,
                work_type=work_type,
                easy_apply=easy_apply,
                sort_by=sort_by,
            )
            if guest_result.get("job_ids"):
                return guest_result
        except Exception as e:
            logger.warning("Guest jobs API fallback failed, using browser route: %s", e)

        base_url = self._build_job_search_url(
            keywords,
            location=location,
            date_posted=date_posted,
            job_type=job_type,
            experience_level=experience_level,
            work_type=work_type,
            easy_apply=easy_apply,
            sort_by=sort_by,
        )
'''
if old not in source:
    raise SystemExit("Could not find search_jobs base_url block to patch")
source = source.replace(old, new, 1)

path.write_text(source)
print(f"Patched LinkedIn job search fallback in {path}")
PY"""
    )
    .env({
        "PATH": "/root/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "PLAYWRIGHT_BROWSERS_PATH": BROWSERS_PATH,
    })
    .run_commands("PLAYWRIGHT_BROWSERS_PATH=/patchright-browsers uvx --from patchright patchright install chromium")
)


@app.function(
    image=image,
    volumes={"/root/.linkedin-mcp": vol},
    secrets=[modal.Secret.from_dict({"PLAYWRIGHT_BROWSERS_PATH": BROWSERS_PATH})],
    # CRITICAL: one browser session only — concurrent requests queue, never parallel
    max_containers=1,
    # Keep one container warm so n8n calls don't cold-start Chromium mid-workflow
    min_containers=1,
    timeout=300,
)
@modal.web_server(8000, startup_timeout=60)
def linkedin_mcp_server():
    """
    Runs mcp-server-linkedin in HTTP transport mode on port 8000.

    Modal exposes this as a public HTTPS endpoint.
    n8n calls: POST https://<your-app>.modal.run/mcp
    """
    import subprocess

    subprocess.Popen(
        [
            "mcp-server-linkedin",   # installed to /root/.local/bin by uv tool install
            "--transport", "streamable-http",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--tool-timeout", "180",  # 3 min per tool call
            "--timeout", "30000",     # 30s per page operation
        ]
    )
