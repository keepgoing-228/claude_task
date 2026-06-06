"""Entry point for the task scheduler MCP server.

Launches the stdio MCP server defined in `app.mcp_server`.

Run directly:
    python main.py

Or as a module (equivalent, kept for MCP client configs):
    python -m app.mcp_server
"""

import asyncio

from app.mcp_server import main


if __name__ == "__main__":
    asyncio.run(main())
