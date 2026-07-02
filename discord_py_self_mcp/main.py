import asyncio
import contextlib
import os
import sys
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource
from discord_py_self_mcp.bot import client
from discord_py_self_mcp.logging_utils import log_to_stderr, mask_secret
from discord_py_self_mcp.tools import registry

app = Server("discord-selfbot-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return registry.get_tool_definitions()


@app.call_tool()
async def call_tool(
    name: str, arguments: dict
) -> list[TextContent | ImageContent | EmbeddedResource]:
    return await registry.call_tool(name, arguments)


def _require_token() -> str:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        sys.stderr.write(
            "Error: DISCORD_TOKEN is not set. Configure it in your MCP client or run "
            "`discord-py-self-mcp-setup`.\n"
        )
        raise SystemExit(1)
    return token


async def run_app():
    token = _require_token()

    log_to_stderr("[STARTUP] Starting Discord connection")
    log_to_stderr(f"[STARTUP] DISCORD_TOKEN: {mask_secret(token)}")

    # Start Discord client in background
    # We don't await it so it doesn't block the MCP server
    asyncio.create_task(client.start(token))

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def run_http(port: int):
    # Shared-daemon mode: one process, one Discord gateway connection, serving
    # any number of MCP clients over streamable HTTP at /mcp. Stateless so each
    # client request is independent - all state lives in the discord client.
    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.routing import Mount

    token = _require_token()

    manager = StreamableHTTPSessionManager(app=app, json_response=True, stateless=True)

    async def handle(scope, receive, send):
        await manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(_starlette):
        log_to_stderr(f"[STARTUP] HTTP mode on 127.0.0.1:{port}/mcp")
        log_to_stderr(f"[STARTUP] DISCORD_TOKEN: {mask_secret(token)}")
        discord_task = asyncio.create_task(client.start(token))
        async with manager.run():
            yield
        discord_task.cancel()

    starlette_app = Starlette(routes=[Mount("/mcp", app=handle)], lifespan=lifespan)
    # Bind loopback only - the selfbot token must not be reachable off-machine.
    uvicorn.run(starlette_app, host="127.0.0.1", port=port, log_level="warning")


def main():
    if "--http" in sys.argv:
        idx = sys.argv.index("--http")
        port = 8602
        if len(sys.argv) > idx + 1:
            try:
                port = int(sys.argv[idx + 1])
            except ValueError:
                pass
        run_http(port)
    else:
        asyncio.run(run_app())


if __name__ == "__main__":
    main()
