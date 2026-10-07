# Cinopsis reach layer - raw lift of Agent-Reach at the pinned sha.
# Upstream logic is verbatim between the LIFT fences; every changed line ends in '# seam:'.
# Gate: python scripts/verify_lift.py

# >>> LIFT agent-reach@a19a171f agent_reach/integrations/__init__.py:1-1
# -*- coding: utf-8 -*-
# <<< LIFT

# >>> LIFT agent-reach@a19a171f agent_reach/integrations/mcp_server.py:1-79
# -*- coding: utf-8 -*-
"""
Agent Reach MCP Server — expose doctor/status as MCP tool.

Run: python -m agent_reach.integrations.mcp_server

Agent Reach is an installer + doctor tool. For actual reading/searching,
agents should call upstream tools directly (twitter-cli, yt-dlp, mcporter, etc.).
"""

import asyncio
import json
import sys

from reach.config import Config  # seam: package import
from reach.core import AgentReach  # seam: package import
from reach.text import scrub_url_credentials  # seam: package import

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    HAS_MCP = True
except ImportError:
    HAS_MCP = False


def create_server():
    if not HAS_MCP:
        print(
            "MCP not installed. Install: python -m pip install "
            "'agent-reach[mcp] @ "
            "https://github.com/Panniantong/agent-reach/archive/main.zip'",
            file=sys.stderr,
        )
        sys.exit(1)

    server = Server("agent-reach")
    config = Config(read_only=True)
    eyes = AgentReach(config)

    @server.list_tools()
    async def list_tools():
        return [
            Tool(name="get_status",
                 description="Get Agent Reach status: which channels are installed and active.",
                 inputSchema={"type": "object", "properties": {}}),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if name == "get_status":
                result = eyes.doctor_report()
            else:
                result = f"Unknown tool: {name}"

            text = json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, (dict, list)) else str(result)
            return [TextContent(type="text", text=text)]
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"Error: {scrub_url_credentials(e)}",
                )
            ]

    return server


async def main():
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
# <<< LIFT
