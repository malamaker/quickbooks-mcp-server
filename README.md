# 🧾 QuickBooks MCP Server

> A secure, local-first Model Context Protocol (MCP) server to query QuickBooks data using natural language inside Claude Desktop.

--- 

## ✅ MCP Review Certification

This MCP Server is **[certified by MCP Review](https://mcpreview.com/mcp-servers/nikhilgy/quickbooks-mcp-server)**.

Being listed and certified on MCP Review ensures this server adheres to MCP standards and best practices, and is trusted by the developer community.

---

## Requirements:
1. Python 3.10 or higher

## Environment Setup
For local development, create a `.env` file in the project root with your QuickBooks credentials:

```bash
# Copy the template and fill in your actual credentials
cp env_template.txt .env
```

Then edit the `.env` file with your actual QuickBooks API credentials:
```
QUICKBOOKS_CLIENT_ID=your_actual_client_id
QUICKBOOKS_CLIENT_SECRET=your_actual_client_secret
QUICKBOOKS_REFRESH_TOKEN=your_actual_refresh_token
QUICKBOOKS_COMPANY_ID=your_actual_company_id
QUICKBOOKS_ENV='sandbox' or 'production'
```

**Note:** The `.env` file is automatically ignored by git for security reasons.

## Step 1. Install uv:
   - MacOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh
   - Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

## Step 2. Configure Claude Desktop
1. Download [Claude Desktop](https://claude.ai/download).
2. Launch Claude and go to Settings > Developer > Edit Config.
3. Modify `claude_desktop_config.json` with:
```json
{
  "mcpServers": {
    "QuickBooks": {
      "command": "uv",
      "args": [
        "--directory",
        "<absolute_path_to_quickbooks_mcp_folder>",
        "run",
        "main_quickbooks_mcp.py"
      ]
    }
  }
}
```
4. Relaunch Claude Desktop.

The first time you open Claude Desktop with these setting it may take
10-20 seconds before the QuickBooks tools appear in the interface due to
the installation of the required packages and the download of the most 
recent QuickBooks API documentation.

Everytime you launch Claude Desktop, the most recent QuickBooks API tools are made available 
to your AI assistant.

## Step 3. Launch Claude Desktop and let your assistant help you
### Examples
**Query Accounts**
```text
Get all accounts from QuickBooks.
```

**Query Bills**
```text
Get all bills from QuickBooks created after 2024-01-01.
```

**Query Customers**
```text
Get all customers from QuickBooks.
```

---

## Docker Setup

The server can be run as a Docker container, which is useful for self-hosted deployments (e.g., Synology NAS).

### Prerequisites
- Docker installed on your host machine
- Your QuickBooks API credentials (Client ID, Client Secret, Refresh Token, Company ID)

### Option A: Build from Source

```bash
# Clone the repository
git clone https://github.com/malamaker/quickbooks-mcp-server.git
cd quickbooks-mcp-server

# Build the image for linux/amd64 (required for Synology)
docker buildx build --platform linux/amd64 -t quickbooks-mcp-server:latest --load .

# Export as a tar file (for transferring to another machine)
docker save quickbooks-mcp-server:latest -o quickbooks-mcp-server.tar
```

### Option B: Load from a Pre-built Tar

If you received a `quickbooks-mcp-server.tar` file:

```bash
docker load -i quickbooks-mcp-server.tar
```

### Running the Container

The server supports two transport modes:

- **stdio** — for local use with Claude Desktop (default when running outside Docker)
- **SSE** — for remote HTTP access (default in Docker), allowing Claude.ai or other clients to connect over the network

#### SSE Mode (Remote Access — Docker Default)

The Docker image defaults to SSE transport on port 8000:

```bash
docker run --rm -p 8000:8000 \
  -e QUICKBOOKS_CLIENT_ID=your_client_id \
  -e QUICKBOOKS_CLIENT_SECRET=your_client_secret \
  -e QUICKBOOKS_REFRESH_TOKEN=your_refresh_token \
  -e QUICKBOOKS_COMPANY_ID=your_company_id \
  -e QUICKBOOKS_ENV=sandbox \
  quickbooks-mcp-server:latest
```

The server will listen on `http://localhost:8000/sse`. You can verify it's running with:

```bash
curl http://localhost:8000/sse
```

#### stdio Mode (Claude Desktop via Docker)

To use stdio transport with Docker (e.g., for Claude Desktop), override the transport:

```bash
docker run --rm -i \
  -e MCP_TRANSPORT=stdio \
  -e QUICKBOOKS_CLIENT_ID=your_client_id \
  -e QUICKBOOKS_CLIENT_SECRET=your_client_secret \
  -e QUICKBOOKS_REFRESH_TOKEN=your_refresh_token \
  -e QUICKBOOKS_COMPANY_ID=your_company_id \
  -e QUICKBOOKS_ENV=sandbox \
  quickbooks-mcp-server:latest
```

#### Transport Environment Variables

| Variable | Default (Docker) | Description |
|---|---|---|
| `MCP_TRANSPORT` | `sse` | Transport mode: `stdio` or `sse` |
| `FASTMCP_HOST` | `0.0.0.0` | Host to bind to (SSE mode only) |
| `FASTMCP_PORT` | `8000` | Port to listen on (SSE mode only) |

Set `QUICKBOOKS_ENV` to `production` when using real QuickBooks data.

### Claude Desktop Config (Docker — stdio)

To use the Docker container with Claude Desktop locally, update your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "QuickBooks": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "MCP_TRANSPORT=stdio",
        "-e", "QUICKBOOKS_CLIENT_ID=your_client_id",
        "-e", "QUICKBOOKS_CLIENT_SECRET=your_client_secret",
        "-e", "QUICKBOOKS_REFRESH_TOKEN=your_refresh_token",
        "-e", "QUICKBOOKS_COMPANY_ID=your_company_id",
        "-e", "QUICKBOOKS_ENV=sandbox",
        "quickbooks-mcp-server:latest"
      ]
    }
  }
}
```

### Connecting Claude.ai (Remote — SSE)

To connect Claude.ai (or any MCP client) to a remotely running SSE server:

1. Run the Docker container with SSE mode (the default) on your server/NAS.
2. Ensure port 8000 is accessible (via port forwarding, reverse proxy, etc.).
3. In Claude.ai, add an MCP server with the URL: `https://your-domain.com/sse`

If using **Nginx Proxy Manager**, create a proxy host pointing to `http://<nas-ip>:8000` with SSL enabled.

---

## Synology Container Manager Setup

These steps walk you through deploying the server on a Synology NAS using Container Manager (Docker).

### 1. Load the Image

1. Transfer `quickbooks-mcp-server.tar` to your Synology (e.g., via SMB share or File Station).
2. Open **Container Manager** > **Image** > **Add** > **Add From File**.
3. Select `quickbooks-mcp-server.tar` and wait for the import to complete.
4. You should see `quickbooks-mcp-server:latest` in your image list.

### 2. Create the Container

1. Go to **Container Manager** > **Container** > **Create**.
2. Select the `quickbooks-mcp-server:latest` image.
3. Name the container (e.g., `quickbooks-mcp`).
4. Under **Advanced Settings** > **Port Settings**, map local port `8000` to container port `8000` (TCP).
5. Under **Advanced Settings** > **Environment**, add these variables:

   | Variable | Value |
   |---|---|
   | `QUICKBOOKS_CLIENT_ID` | Your QuickBooks Client ID |
   | `QUICKBOOKS_CLIENT_SECRET` | Your QuickBooks Client Secret |
   | `QUICKBOOKS_REFRESH_TOKEN` | Your QuickBooks Refresh Token |
   | `QUICKBOOKS_COMPANY_ID` | Your QuickBooks Company ID |
   | `QUICKBOOKS_ENV` | `sandbox` or `production` |
   | `MCP_TRANSPORT` | `sse` (default) |
   | `FASTMCP_PORT` | `8000` (default) |

6. Click **Apply** to create the container.

### 3. Notes

- The image is built for `linux/amd64`, which is compatible with most Synology NAS models.
- The Docker image defaults to SSE transport on port 8000. Use Nginx Proxy Manager or Synology's reverse proxy to expose it with SSL.
- Store your credentials securely. Do not commit `.env` files or credentials to version control.
- To update the server, rebuild the tar from the latest source and re-import it via Container Manager.
