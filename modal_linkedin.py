"""Centralized LinkedIn MCP server on Modal.

All LinkedIn-backed workflows call this one streamable-HTTP MCP service. The
only authenticated browser profile lives in ``linkedin-mcp-vol``. Caller apps
must not mount or copy LinkedIn session data into their own volumes.
"""

import modal


app = modal.App("linkedin-mcp")
session_volume = modal.Volume.from_name("linkedin-mcp-vol", create_if_missing=True)
BROWSERS_PATH = "/patchright-browsers"
MCP_VERSION = "4.19.0"
PATCHRIGHT_VERSION = "1.61.2"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install(
        "libnss3", "libnspr4", "libatk1.0-0", "libatk-bridge2.0-0", "libcups2",
        "libdrm2", "libdbus-1-3", "libxkbcommon0", "libxcomposite1", "libxdamage1",
        "libxfixes3", "libxrandr2", "libgbm1", "libasound2", "libpango-1.0-0", "libcairo2",
    )
    .pip_install(
        "uv==0.11.2",
        "fastapi==0.116.1",
        "httpx==0.28.1",
    )
    .run_commands(
        f"uv tool install mcp-server-linkedin=={MCP_VERSION} "
        f"--with patchright=={PATCHRIGHT_VERSION}"
    )
    .env({
        "PATH": "/root/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "PLAYWRIGHT_BROWSERS_PATH": BROWSERS_PATH,
    })
    .run_commands(
        "PLAYWRIGHT_BROWSERS_PATH=/patchright-browsers "
        f"uvx --from patchright=={PATCHRIGHT_VERSION} patchright install chromium"
    )
)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("linkedin-mcp-auth")],
    volumes={"/root/.linkedin-mcp": session_volume},
    max_containers=1,
    min_containers=1,
    timeout=300,
)
@modal.asgi_app()
def linkedin_mcp_server():
    """Protect and proxy the pinned MCP package as the single browser owner."""
    import hmac
    import os
    import socket
    import subprocess
    import time

    import httpx
    from fastapi import FastAPI, Header, HTTPException, Request, Response

    subprocess.Popen([
        "mcp-server-linkedin",
        "--transport", "streamable-http",
        "--host", "127.0.0.1",
        "--port", "8001",
        "--tool-timeout", "180",
        "--timeout", "30000",
        "--no-auto-import",
    ])

    deadline = time.monotonic() + 30
    while True:
        try:
            with socket.create_connection(("127.0.0.1", 8001), timeout=1):
                break
        except OSError:
            if time.monotonic() >= deadline:
                raise RuntimeError("LinkedIn MCP process did not become ready")
            time.sleep(0.25)

    web = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @web.api_route("/mcp", methods=["POST", "DELETE"])
    async def authenticated_proxy(
        request: Request,
        authorization: str = Header(default=""),
    ) -> Response:
        expected = os.environ.get("LINKEDIN_MCP_TOKEN", "").strip()
        supplied = authorization.removeprefix("Bearer ").strip()
        if not expected:
            raise HTTPException(status_code=500, detail="Missing MCP credential")
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="Unauthorized")

        upstream_headers = {
            "Content-Type": request.headers.get("content-type", "application/json"),
            "Accept": request.headers.get(
                "accept", "application/json, text/event-stream"
            ),
        }
        session_id = request.headers.get("mcp-session-id", "")
        if session_id:
            upstream_headers["Mcp-Session-Id"] = session_id

        async with httpx.AsyncClient(timeout=240) as client:
            upstream = await client.request(
                request.method,
                "http://127.0.0.1:8001/mcp",
                content=await request.body(),
                headers=upstream_headers,
            )
        response_headers = {}
        for name in ("content-type", "mcp-session-id"):
            if value := upstream.headers.get(name):
                response_headers[name] = value
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=response_headers,
        )

    return web
