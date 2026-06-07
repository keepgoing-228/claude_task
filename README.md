# Claude Task Scheduler Prototype

A real MCP (Model Context Protocol) server that lets Claude — or any MCP client — schedule and manage tasks via standardized tool calls.

> Restructured from the reference prototype at
> [bohr109/build-moat-live-sessions — `chatgpt_task/answers`](https://github.com/bohr109/build-moat-live-sessions/tree/main/chatgpt_task/answers).

## Key Design Decisions

1. **Watcher + Queue + Worker** — Decoupled architecture: watcher scans DB for due jobs, pushes to queue, workers execute independently (in-memory queue simulates SQS)
2. **Time Bucket Partitioning** — Jobs partitioned by hour (`YYYYMMDDHH`) so the watcher only scans the relevant partition
3. **MCP Tool Registry Pattern** — `TOOL_REGISTRY` dict routes tool calls to handlers (vs if-else anti-pattern)
4. **Namespace + Action Verb Naming** — `task.create`, `task.status` for better LLM tool selection accuracy

## MCP Tools

| Tool | Description |
|------|-------------|
| `task.create` | Schedule a new task for future execution |
| `task.list` | List all scheduled tasks |
| `task.status` | Get the status of a scheduled task |
| `task.cancel` | Cancel a scheduled task |

**Time zones:** `scheduled_at` is ISO 8601. A timezone offset is honored and converted to UTC (e.g. `2026-05-03T10:00:00+08:00` → `02:00:00Z`); a naive timestamp with no offset is interpreted as UTC. Times are stored and compared in UTC.

## Setup

Dependencies are declared in `pyproject.toml`. With [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

Run the server directly:

```bash
python main.py          # or: python -m app.mcp_server
```

## Verify with mcp-inspector (recommended first)

`mcp-inspector` is the official MCP testing GUI — no Claude needed. Requires Node.js (for `npx`).

```bash
npx @modelcontextprotocol/inspector python -m app.mcp_server
```

This opens a browser UI (usually `http://localhost:5173`). Steps:

1. Click **Connect** — should show 4 tools listed
2. Click **task.create** -> fill in `description` and `scheduled_at` (ISO 8601, e.g. `2026-05-03T10:00:00`) -> **Run Tool** -> see `{"job_id": 1, ...}`
3. Click **task.status** -> fill in `job_id: 1` -> see status info
4. Click **task.list** -> see all jobs

If all 4 tools work in inspector, the server is correct — proceed to Claude integration.

## Connect to Claude Desktop

Edit Claude Desktop's config file:

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

Add this entry (use **absolute paths**):

```json
{
  "mcpServers": {
    "task-scheduler": {
      "command": "/absolute/path/to/claude_task/.venv/bin/python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/absolute/path/to/claude_task"
    }
  }
}
```

Then **fully quit and restart** Claude Desktop. You should see a 🔨 icon in the chat input — click to verify the 4 tools appear.

## Connect to Claude Code

Either edit `.claude/settings.json` (project-scoped) or `~/.claude/settings.json` (global) with the same `mcpServers` block, or run:

```bash
claude mcp add task-scheduler /absolute/path/to/claude_task/.venv/bin/python -m app.mcp_server
```

(Run from the repo root so `cwd` resolves correctly, or pass `--cwd`.)

## Try It

Once connected to Claude Desktop or Claude Code, talk to Claude:

> "Schedule a task to review PR #123 tomorrow at 9am."
>
> Claude calls `task.create` -> returns job_id.
>
> "What's the status of that task?"
>
> Claude calls `task.status` -> returns the job state.
>
> "List everything I've scheduled."
>
> Claude calls `task.list`.

## Project Structure

```
.
├── main.py          # Entry point — launches the stdio MCP server
├── pyproject.toml   # Project metadata + dependencies (mcp, sqlalchemy)
└── app/
    ├── __init__.py
    ├── mcp_server.py    # Tool handlers + Tool definitions + registry + MCP entry point
    ├── scheduler.py     # Watcher (time bucket scan) + Worker + Queue
    ├── models.py        # SQLAlchemy DB models (jobs with time_bucket)
    └── database.py      # SQLite connection
```

## Troubleshooting

- **Tools don't appear in Claude Desktop / Code** — check the config path is absolute, the venv Python path is correct, and that Claude was fully restarted (not just window-closed).
- **`mcp-inspector` shows "failed to connect"** — run `python -m app.mcp_server` directly first to see if there's an import or DB error. The MCP stdio protocol uses stdout, so any `print()` in your code will break it; check for stray prints.
- **`stdio` log noise** — MCP uses stdout for protocol messages. If you add logging, write to stderr (`logging.basicConfig(stream=sys.stderr)`) or a file, never stdout.
