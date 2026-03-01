# QuickBooks MCP Server

> [!WARNING]
> This tool directly reads, creates, modifies, and deletes live QuickBooks financial data. Incorrect categorizations could affect tax filings and financial records. The automated scheduler makes changes without per-action human approval. **Read [DISCLAIMER.md](DISCLAIMER.md) before deploying. Use at your own risk.**

> A self-hosted Model Context Protocol (MCP) server for QuickBooks with an admin portal, automated transaction categorization scheduler, and AI-powered bookkeeping via Claude.

---

## Architecture

```
Single Docker Container
├── main_quickbooks_mcp.py     (entrypoint — starts both servers via asyncio.gather)
├── MCP Server (port 8080)     (Streamable HTTP — external via Nginx Proxy Manager)
├── Admin Portal (port 8888)   (FastAPI + Jinja2 — internal LAN only)
├── APScheduler                (AsyncIOScheduler — shared event loop)
└── /app/data/                 (volume-mounted persistent storage)
    ├── quickbooks_mcp.db      (SQLite database)
    ├── rules.json             (default categorization rules)
    ├── scheduler.log          (scheduler run logs)
    └── .secret_key            (auto-generated Fernet encryption key)
```

**Ports:**
- **8080** — MCP server (Streamable HTTP). Expose externally via Nginx Proxy Manager for Claude.ai / remote MCP clients.
- **8888** — Admin portal (FastAPI). Keep internal / LAN-only for management.

---

## Requirements

- Python 3.12+
- Docker (for containerized deployment)

---

## Quick Start (Docker Compose)

1. Clone the repo and create a `.env` file:
```bash
git clone https://github.com/malamaker/quickbooks-mcp-server.git
cd quickbooks-mcp-server
cp env_template.txt .env
# Edit .env with your QuickBooks credentials
```

2. Start with Docker Compose:
```bash
docker compose up -d
```

3. Access the admin portal at `http://localhost:8888`
   - Default login: `admin` / `admin123`
   - You'll be forced to change your password on first login

4. Connect MCP clients to `http://localhost:8080/mcp`

---

## Environment Setup

Create a `.env` file from the template:

```bash
cp env_template.txt .env
```

| Variable | Default | Description |
|---|---|---|
| `QUICKBOOKS_CLIENT_ID` | — | QuickBooks OAuth Client ID |
| `QUICKBOOKS_CLIENT_SECRET` | — | QuickBooks OAuth Client Secret |
| `QUICKBOOKS_REFRESH_TOKEN` | — | QuickBooks OAuth Refresh Token |
| `QUICKBOOKS_COMPANY_ID` | — | QuickBooks Company/Realm ID |
| `QUICKBOOKS_ENV` | `sandbox` | `sandbox` or `production` |
| `MCP_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `FASTMCP_HOST` | `0.0.0.0` | Host to bind (HTTP mode) |
| `FASTMCP_PORT` | `8080` | MCP server port (HTTP mode) |
| `SECRET_KEY` | auto-generated | Fernet encryption key for sensitive DB fields |
| `DATA_DIR` | `/app/data` | Persistent data directory |

---

## Local Development

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Run in stdio mode (default — for Claude Desktop)
uv run python main_quickbooks_mcp.py

# Run in HTTP mode (MCP + Admin Portal + Scheduler)
MCP_TRANSPORT=streamable-http DATA_DIR=./data uv run python main_quickbooks_mcp.py
```

### Claude Desktop Configuration

```json
{
  "mcpServers": {
    "QuickBooks": {
      "command": "uv",
      "args": [
        "--directory", "<absolute_path_to_quickbooks_mcp_folder>",
        "run", "main_quickbooks_mcp.py"
      ]
    }
  }
}
```

---

## Admin Portal

The admin portal at port 8888 provides:

- **Dashboard** — Scheduler status, stats, recent run history
- **Flagged Items** — Review and resolve AI-flagged transactions
- **Rules** — Manage categorization rules (CRUD, import/export JSON)
- **Scheduler** — Configure cron schedule, Anthropic API key, trigger manual runs
- **Settings** — QuickBooks credentials, password management

### First Login

1. Navigate to `http://localhost:8888`
2. Login with `admin` / `admin123`
3. Change your password (required on first login)

### Scheduler

The scheduler uses APScheduler to run AI-powered transaction categorization on a cron schedule:

1. Go to **Scheduler** page
2. Enter your Anthropic API key and test it
3. Set a cron schedule (default: `0 23 * * *` = daily at 11 PM)
4. Enable the scheduler
5. Optionally click **Run Now** for an immediate run

The categorization workflow:
1. Pulls uncategorized transactions from QuickBooks
2. Loads enabled rules from the database
3. Sends transactions + rules to Claude for AI categorization
4. Applies categorizations back to QuickBooks
5. Flags suspicious/ambiguous items for manual review
6. Saves learned rules suggested by Claude

---

## Docker

### Build from Source

```bash
# Build for linux/amd64 (Synology deployment)
docker buildx build --platform linux/amd64 \
  -t quickbooks-mcp-server:0.2.0 \
  -t quickbooks-mcp-server:latest \
  --load .

# Export as tar (dual-tagged)
docker save quickbooks-mcp-server:0.2.0 quickbooks-mcp-server:latest \
  -o quickbooks-mcp-server.tar
```

### Docker Compose

```bash
# Start
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

### Manual Docker Run

```bash
docker run -d --name quickbooks-mcp \
  -p 8080:8080 -p 8888:8888 \
  -v ./data:/app/data \
  -e QUICKBOOKS_CLIENT_ID=your_id \
  -e QUICKBOOKS_CLIENT_SECRET=your_secret \
  -e QUICKBOOKS_REFRESH_TOKEN=your_token \
  -e QUICKBOOKS_COMPANY_ID=your_company_id \
  -e QUICKBOOKS_ENV=sandbox \
  quickbooks-mcp-server:latest
```

### stdio Mode (Claude Desktop via Docker)

```bash
docker run --rm -i \
  -e MCP_TRANSPORT=stdio \
  -e QUICKBOOKS_CLIENT_ID=your_id \
  -e QUICKBOOKS_CLIENT_SECRET=your_secret \
  -e QUICKBOOKS_REFRESH_TOKEN=your_token \
  -e QUICKBOOKS_COMPANY_ID=your_company_id \
  quickbooks-mcp-server:latest
```

---

## Synology NAS Deployment

### 1. Load the Image

1. Transfer `quickbooks-mcp-server.tar` to your Synology.
2. Open **Container Manager** > **Image** > **Add** > **Add From File**.
3. Select the tar file and import.

### 2. Create the Container

1. Go to **Container Manager** > **Container** > **Create**.
2. Select `quickbooks-mcp-server:latest`.
3. **Port Settings**: Map `8080:8080` and `8888:8888`.
4. **Volume**: Map a local folder to `/app/data` for persistent storage.
5. **Environment Variables**: Set your QuickBooks credentials.
6. Click **Apply**.

### 3. Network Setup

- **Port 8080** (MCP): Expose via Nginx Proxy Manager with SSL for remote Claude.ai access.
- **Port 8888** (Admin): Keep LAN-only. Do not expose to the internet.

---

## MCP Tools

| Tool | Description |
|---|---|
| `get_quickbooks_entity_schema` | Get field schema for a QuickBooks entity |
| `query_quickbooks` | Execute SQL-like queries on QuickBooks |
| `update_categorization_rules` | Save AI-learned categorization rules to the database |
| Auto-registered API tools | All QuickBooks REST API endpoints |

---

## Legal & Responsibility

> [!IMPORTANT]
> Please read **[DISCLAIMER.md](DISCLAIMER.md)** in full before deploying this software.

This is an independent open source project, **not affiliated with or endorsed by Intuit or Anthropic**. Key points:

- This tool can **read, create, modify, and delete** financial data in your QuickBooks account. Changes are real and may be irreversible.
- The automated scheduler modifies QuickBooks data **without human approval for each action**. Maintain backups and review results regularly.
- AI-powered categorization is **not a substitute for a licensed accountant or bookkeeper**. Always have a qualified professional review your financial records.
- The authors and contributors accept **no responsibility** for data loss, incorrect categorizations, tax filing errors, audit issues, or any financial harm.
- **Test in QuickBooks Sandbox first** before connecting to production data.
- This software is provided **"AS IS"** without warranty of any kind.

See [DISCLAIMER.md](DISCLAIMER.md) for the complete disclaimer, including data privacy considerations and detailed risk information.

---

## MCP Review Certification

This MCP Server is **[certified by MCP Review](https://mcpreview.com/mcp-servers/nikhilgy/quickbooks-mcp-server)**.
