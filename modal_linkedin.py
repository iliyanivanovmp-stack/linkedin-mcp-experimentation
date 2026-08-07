"""Centralized LinkedIn MCP server on Modal.

All LinkedIn-backed workflows call this one streamable-HTTP MCP service. The
only authenticated browser profile lives in ``linkedin-mcp-vol``. Caller apps
must not mount or copy LinkedIn session data into their own volumes.
"""

import modal


app = modal.App("linkedin-mcp")
session_volume = modal.Volume.from_name("linkedin-mcp-vol", create_if_missing=True)
BROWSERS_PATH = "/patchright-browsers"
MCP_VERSION = "4.16.1"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install(
        "libnss3", "libnspr4", "libatk1.0-0", "libatk-bridge2.0-0", "libcups2",
        "libdrm2", "libdbus-1-3", "libxkbcommon0", "libxcomposite1", "libxdamage1",
        "libxfixes3", "libxrandr2", "libgbm1", "libasound2", "libpango-1.0-0", "libcairo2",
    )
    .pip_install("uv==0.11.2")
    .run_commands(
        f"uv tool install mcp-server-linkedin=={MCP_VERSION} "
        "--with patchright==1.60.1"
    )
    .env({
        "PATH": "/root/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "PLAYWRIGHT_BROWSERS_PATH": BROWSERS_PATH,
    })
    .run_commands(
        "PLAYWRIGHT_BROWSERS_PATH=/patchright-browsers "
        "uvx --from patchright==1.60.1 patchright install chromium"
    )
)


@app.function(
    image=image,
    volumes={"/root/.linkedin-mcp": session_volume},
    max_containers=1,
    min_containers=1,
    timeout=300,
)
@modal.web_server(8000, startup_timeout=60)
def linkedin_mcp_server():
    """Run the unmodified, pinned MCP package as the single browser owner."""
    import subprocess

    subprocess.Popen([
        "mcp-server-linkedin",
        "--transport", "streamable-http",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--tool-timeout", "180",
        "--timeout", "30000",
        "--no-auto-import",
    ])
