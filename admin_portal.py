"""Admin portal — FastAPI + Jinja2, session auth, CSRF."""

import json
import os
import asyncio
import traceback
from pathlib import Path
from functools import wraps

from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature

import database as db

# ---------------------------------------------------------------------------
# Chat — Tool definitions for Anthropic API
# ---------------------------------------------------------------------------

CHAT_TOOLS = [
    {
        "name": "get_quickbooks_entity_schema",
        "description": "Fetches the schema for a given QuickBooks entity (e.g., 'Bill', 'Customer'). Use this to understand available fields before querying.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_name": {"type": "string", "description": "The QuickBooks entity name, e.g. 'Bill', 'Customer', 'Invoice'"}
            },
            "required": ["entity_name"]
        }
    },
    {
        "name": "query_quickbooks",
        "description": "Executes a SQL-like SELECT query on a QuickBooks entity. Always use get_quickbooks_entity_schema first to learn the available fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "SQL-like query, e.g. SELECT * FROM Customer"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "update_categorization_rules",
        "description": "Save categorization rules to the database. Accepts a JSON array of rule objects with: rule_type, pattern, category, description.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rules": {"type": "string", "description": "JSON array of rule objects"}
            },
            "required": ["rules"]
        }
    },
]


async def _execute_tool_async(name: str, tool_input: dict) -> str:
    """Async wrapper for tool execution."""
    from main_quickbooks_mcp import get_quickbooks_entity_schema, query_quickbooks, update_categorization_rules
    try:
        if name == "get_quickbooks_entity_schema":
            result = get_quickbooks_entity_schema(**tool_input)
        elif name == "query_quickbooks":
            result = query_quickbooks(**tool_input)
        elif name == "update_categorization_rules":
            result = await update_categorization_rules(**tool_input)
        else:
            return f"Unknown tool: {name}"
        return result.text if hasattr(result, 'text') else str(result)
    except Exception as e:
        return f"Tool error: {e}"


def _build_api_messages(db_messages: list[dict]) -> list[dict]:
    """Convert DB chat_messages rows into Anthropic API message format.

    Merges assistant text + adjacent tool_call rows into a single assistant
    message with text + tool_use content blocks (required by the API).
    """
    api_messages = []
    i = 0
    while i < len(db_messages):
        msg = db_messages[i]
        role = msg["role"]

        if role == "user":
            api_messages.append({"role": "user", "content": msg["content"]})
            i += 1

        elif role == "assistant":
            # Check if followed by tool_call — merge into one assistant message
            if i + 1 < len(db_messages) and db_messages[i + 1]["role"] == "tool_call":
                content_blocks = [{"type": "text", "text": msg["content"]}]
                i += 1
                while i < len(db_messages) and db_messages[i]["role"] == "tool_call":
                    tc = db_messages[i]
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["tool_call_id"],
                        "name": tc["tool_name"],
                        "input": json.loads(tc["content"]),
                    })
                    i += 1
                api_messages.append({"role": "assistant", "content": content_blocks})
                # Collect tool_result entries
                result_blocks = []
                while i < len(db_messages) and db_messages[i]["role"] == "tool_result":
                    tr = db_messages[i]
                    result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": tr["tool_call_id"],
                        "content": tr["content"],
                    })
                    i += 1
                if result_blocks:
                    api_messages.append({"role": "user", "content": result_blocks})
            else:
                api_messages.append({"role": "assistant", "content": msg["content"]})
                i += 1

        elif role == "tool_call":
            # Tool calls without preceding text
            content_blocks = []
            while i < len(db_messages) and db_messages[i]["role"] == "tool_call":
                tc = db_messages[i]
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc["tool_call_id"],
                    "name": tc["tool_name"],
                    "input": json.loads(tc["content"]),
                })
                i += 1
            api_messages.append({"role": "assistant", "content": content_blocks})

            # Collect matching tool_result entries
            result_blocks = []
            while i < len(db_messages) and db_messages[i]["role"] == "tool_result":
                tr = db_messages[i]
                result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tr["tool_call_id"],
                    "content": tr["content"],
                })
                i += 1
            if result_blocks:
                api_messages.append({"role": "user", "content": result_blocks})

        elif role == "tool_result":
            # Orphan tool_result (shouldn't happen but handle gracefully)
            api_messages.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": msg["tool_call_id"], "content": msg["content"]}]
            })
            i += 1
        else:
            i += 1

    return api_messages


CHAT_SYSTEM_PROMPT = (
    "You are a QuickBooks assistant. You help users query and manage their QuickBooks data. "
    "Use the available tools to look up entity schemas and run queries. "
    "Always check the schema before querying an entity. Be concise and helpful."
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

SESSION_MAX_AGE = 8 * 3600  # 8 hours
_serializer = None


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        from crypto import _get_fernet
        # Use the Fernet key as the signing secret
        _get_fernet()
        secret = os.environ.get("SECRET_KEY", "changeme-default-secret")
        # Also try reading from the auto-generated key file
        key_path = Path(os.environ.get("DATA_DIR", "/app/data")) / ".secret_key"
        if secret == "changeme-default-secret" and key_path.exists():
            secret = key_path.read_text().strip()
        _serializer = URLSafeTimedSerializer(secret)
    return _serializer


def _get_session(request: Request) -> dict | None:
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        return _get_serializer().loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None


def _set_session(response, data: dict):
    token = _get_serializer().dumps(data)
    response.set_cookie(
        "session", token, httponly=True, samesite="strict", max_age=SESSION_MAX_AGE
    )


def _generate_csrf() -> str:
    import secrets
    return secrets.token_hex(32)


def _verify_csrf(request_token: str, session_token: str) -> bool:
    if not request_token or not session_token:
        return False
    return request_token == session_token


# Flash message helpers
def _set_flash(request: Request, message: str, category: str = "info"):
    if not hasattr(request.state, "_flashes"):
        request.state._flashes = []
    request.state._flashes.append({"message": message, "category": category})


def _get_flashes(request: Request) -> list:
    return getattr(request.state, "_flashes", [])


# Store flashes in cookie for redirect scenarios
def _flash_to_cookie(response, flashes: list):
    if flashes:
        response.set_cookie("_flashes", json.dumps(flashes), httponly=True, samesite="strict", max_age=10)


def _flash_from_cookie(request: Request) -> list:
    raw = request.cookies.get("_flashes")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return []


def _clear_flash_cookie(response):
    response.delete_cookie("_flashes")


def _ctx(request: Request, session: dict, extra: dict = None) -> dict:
    """Build template context with session, CSRF, and flashes."""
    csrf = _generate_csrf()
    # Store CSRF in session
    sess = dict(session)
    sess["csrf"] = csrf
    ctx = {
        "request": request,
        "session": sess,
        "csrf_token": csrf,
        "flashes": _flash_from_cookie(request),
    }
    if extra:
        ctx.update(extra)
    return ctx


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Disclaimer (public — no auth required)
# ---------------------------------------------------------------------------

@app.get("/disclaimer", response_class=HTMLResponse)
async def disclaimer_page(request: Request):
    session = _get_session(request)
    ctx = {"request": request, "session": session, "flashes": _flash_from_cookie(request)}
    resp = templates.TemplateResponse("disclaimer.html", ctx)
    _clear_flash_cookie(resp)
    return resp


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    session = _get_session(request)
    if session:
        return RedirectResponse("/", status_code=302)
    ctx = {"request": request, "flashes": _flash_from_cookie(request)}
    resp = templates.TemplateResponse("login.html", ctx)
    _clear_flash_cookie(resp)
    return resp


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = await db.verify_password(username, password)
    if not user:
        resp = RedirectResponse("/login", status_code=302)
        _flash_to_cookie(resp, [{"message": "Invalid username or password.", "category": "error"}])
        return resp

    session_data = {"user_id": user["id"], "username": user["username"], "must_change_password": bool(user["must_change_password"])}
    if user["must_change_password"]:
        dest = "/change-password"
    else:
        ack = await db.get_setting("disclaimer_accepted_at")
        dest = "/" if ack else "/acknowledge"
    resp = RedirectResponse(dest, status_code=302)
    _set_session(resp, session_data)
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("session")
    return resp


@app.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request):
    session = _get_session(request)
    if not session:
        return RedirectResponse("/login", status_code=302)
    ctx = _ctx(request, session)
    resp = templates.TemplateResponse("change_password.html", ctx)
    _set_session(resp, session)
    _clear_flash_cookie(resp)
    return resp


@app.post("/change-password")
async def change_password_submit(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(""),
):
    session = _get_session(request)
    if not session:
        return RedirectResponse("/login", status_code=302)

    if new_password != confirm_password:
        resp = RedirectResponse("/change-password", status_code=302)
        _flash_to_cookie(resp, [{"message": "Passwords do not match.", "category": "error"}])
        _set_session(resp, session)
        return resp

    if len(new_password) < 8:
        resp = RedirectResponse("/change-password", status_code=302)
        _flash_to_cookie(resp, [{"message": "Password must be at least 8 characters.", "category": "error"}])
        _set_session(resp, session)
        return resp

    await db.change_password(session["user_id"], new_password)
    session["must_change_password"] = False
    # Check if disclaimer has been acknowledged
    ack = await db.get_setting("disclaimer_accepted_at")
    if ack:
        dest = "/"
    else:
        dest = "/acknowledge"
    resp = RedirectResponse(dest, status_code=302)
    _set_session(resp, session)
    _flash_to_cookie(resp, [{"message": "Password changed successfully.", "category": "success"}])
    return resp


# ---------------------------------------------------------------------------
# Disclaimer Acknowledgment
# ---------------------------------------------------------------------------

@app.get("/acknowledge", response_class=HTMLResponse)
async def acknowledge_page(request: Request):
    session = _get_session(request)
    if not session:
        return RedirectResponse("/login", status_code=302)
    # If already acknowledged, go to dashboard
    ack = await db.get_setting("disclaimer_accepted_at")
    if ack:
        return RedirectResponse("/", status_code=302)
    ctx = _ctx(request, session)
    resp = templates.TemplateResponse("acknowledge.html", ctx)
    _set_session(resp, session)
    _clear_flash_cookie(resp)
    return resp


@app.post("/acknowledge")
async def acknowledge_submit(request: Request, csrf_token: str = Form("")):
    session = _get_session(request)
    if not session:
        return RedirectResponse("/login", status_code=302)
    from datetime import datetime, timezone
    await db.set_setting("disclaimer_accepted_at", datetime.now(timezone.utc).isoformat())
    resp = RedirectResponse("/", status_code=302)
    _set_session(resp, session)
    _flash_to_cookie(resp, [{"message": "Disclaimer acknowledged. Welcome to the admin portal.", "category": "success"}])
    return resp


def require_auth(func):
    """Decorator to require authenticated session."""
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        session = _get_session(request)
        if not session:
            return RedirectResponse("/login", status_code=302)
        if session.get("must_change_password"):
            return RedirectResponse("/change-password", status_code=302)
        request.state.session = session
        return await func(request, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
@require_auth
async def dashboard(request: Request):
    stats = await db.get_dashboard_stats()
    config = await db.get_scheduler_config()
    recent_runs = await db.get_recent_runs(limit=5)
    ctx = _ctx(request, request.state.session, {
        "stats": stats, "config": config, "recent_runs": recent_runs
    })
    resp = templates.TemplateResponse("dashboard.html", ctx)
    _set_session(resp, request.state.session)
    _clear_flash_cookie(resp)
    return resp


# ---------------------------------------------------------------------------
# Run Now
# ---------------------------------------------------------------------------

@app.post("/run-now")
@require_auth
async def run_now(request: Request):
    from scheduler_engine import run_categorization
    asyncio.create_task(run_categorization("manual"))
    return JSONResponse({"status": "started", "message": "Categorization run started."})


# ---------------------------------------------------------------------------
# Flagged Items
# ---------------------------------------------------------------------------

@app.get("/flagged", response_class=HTMLResponse)
@require_auth
async def flagged_list(request: Request):
    status_filter = request.query_params.get("status")
    items = await db.get_flagged_items(status_filter)
    ctx = _ctx(request, request.state.session, {
        "items": items, "current_filter": status_filter
    })
    resp = templates.TemplateResponse("flagged.html", ctx)
    _set_session(resp, request.state.session)
    _clear_flash_cookie(resp)
    return resp


@app.post("/flagged/resolve")
@require_auth
async def resolve_item(request: Request, item_id: int = Form(...), status: str = Form(...), notes: str = Form("")):
    await db.resolve_flagged_item(item_id, status, notes)
    resp = RedirectResponse("/flagged", status_code=302)
    _flash_to_cookie(resp, [{"message": "Item resolved.", "category": "success"}])
    return resp


@app.post("/flagged/bulk-resolve")
@require_auth
async def bulk_resolve(request: Request, status: str = Form(...), notes: str = Form("")):
    form = await request.form()
    item_ids = [int(v) for k, v in form.multi_items() if k == "item_ids"]
    if item_ids:
        await db.bulk_resolve_flagged(item_ids, status, notes)
    resp = RedirectResponse("/flagged", status_code=302)
    _flash_to_cookie(resp, [{"message": f"{len(item_ids)} items resolved.", "category": "success"}])
    return resp


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

@app.get("/rules", response_class=HTMLResponse)
@require_auth
async def rules_list(request: Request):
    rules = await db.get_rules()
    # Group by rule_type
    grouped = {}
    for r in rules:
        grouped.setdefault(r["rule_type"], []).append(r)
    ctx = _ctx(request, request.state.session, {"grouped_rules": grouped, "rules": rules})
    resp = templates.TemplateResponse("rules.html", ctx)
    _set_session(resp, request.state.session)
    _clear_flash_cookie(resp)
    return resp


@app.post("/rules")
@require_auth
async def create_rule(
    request: Request,
    rule_type: str = Form(...),
    pattern: str = Form(...),
    category: str = Form(""),
    description: str = Form(""),
):
    await db.create_rule(rule_type, pattern, category or None, description or None)
    resp = RedirectResponse("/rules", status_code=302)
    _flash_to_cookie(resp, [{"message": "Rule created.", "category": "success"}])
    return resp


@app.post("/rules/{rule_id}")
@require_auth
async def update_rule(
    request: Request,
    rule_id: int,
    rule_type: str = Form(...),
    pattern: str = Form(...),
    category: str = Form(""),
    description: str = Form(""),
):
    await db.update_rule(rule_id, rule_type=rule_type, pattern=pattern,
                         category=category or None, description=description or None)
    resp = RedirectResponse("/rules", status_code=302)
    _flash_to_cookie(resp, [{"message": "Rule updated.", "category": "success"}])
    return resp


@app.post("/rules/{rule_id}/delete")
@require_auth
async def delete_rule(request: Request, rule_id: int):
    await db.delete_rule(rule_id)
    resp = RedirectResponse("/rules", status_code=302)
    _flash_to_cookie(resp, [{"message": "Rule deleted.", "category": "success"}])
    return resp


@app.post("/rules/toggle/{rule_id}")
@require_auth
async def toggle_rule(request: Request, rule_id: int):
    await db.toggle_rule(rule_id)
    return JSONResponse({"status": "ok"})


@app.get("/rules/export")
@require_auth
async def export_rules(request: Request):
    rules = await db.export_rules()
    content = json.dumps(rules, indent=2)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=rules.json"},
    )


@app.post("/rules/import")
@require_auth
async def import_rules(request: Request, file: UploadFile = File(...)):
    try:
        content = await file.read()
        rules = json.loads(content)
        await db.import_rules(rules)
        resp = RedirectResponse("/rules", status_code=302)
        _flash_to_cookie(resp, [{"message": f"Imported {len(rules)} rules.", "category": "success"}])
    except Exception as e:
        resp = RedirectResponse("/rules", status_code=302)
        _flash_to_cookie(resp, [{"message": f"Import failed: {e}", "category": "error"}])
    return resp


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

@app.get("/scheduler", response_class=HTMLResponse)
@require_auth
async def scheduler_page(request: Request):
    config = await db.get_scheduler_config()
    runs = await db.get_recent_runs(limit=20)
    ctx = _ctx(request, request.state.session, {"config": config, "runs": runs})
    resp = templates.TemplateResponse("scheduler.html", ctx)
    _set_session(resp, request.state.session)
    _clear_flash_cookie(resp)
    return resp


@app.post("/scheduler")
@require_auth
async def scheduler_update(
    request: Request,
    enabled: str = Form("off"),
    schedule_cron: str = Form("0 23 * * *"),
    anthropic_api_key: str = Form(""),
):
    kwargs = {
        "enabled": 1 if enabled == "on" else 0,
        "schedule_cron": schedule_cron,
    }
    if anthropic_api_key:
        kwargs["anthropic_api_key"] = anthropic_api_key

    await db.update_scheduler_config(**kwargs)

    # Reconfigure the live scheduler
    try:
        from scheduler_engine import reconfigure_scheduler
        await reconfigure_scheduler()
    except Exception:
        pass

    resp = RedirectResponse("/scheduler", status_code=302)
    _flash_to_cookie(resp, [{"message": "Scheduler configuration updated.", "category": "success"}])
    return resp


@app.post("/scheduler/test-api-key")
@require_auth
async def test_api_key(request: Request, anthropic_api_key: str = Form(...)):
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
        resp = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=10,
            messages=[{"role": "user", "content": "Say OK"}],
        )
        return JSONResponse({"status": "ok", "message": "API key is valid."})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.get("/settings", response_class=HTMLResponse)
@require_auth
async def settings_page(request: Request):
    ctx = _ctx(request, request.state.session)
    resp = templates.TemplateResponse("settings.html", ctx)
    _set_session(resp, request.state.session)
    _clear_flash_cookie(resp)
    return resp


@app.post("/settings/quickbooks")
@require_auth
async def update_qb_settings(
    request: Request,
    client_id: str = Form(""),
    client_secret: str = Form(""),
    refresh_token: str = Form(""),
    company_id: str = Form(""),
    qb_env: str = Form("sandbox"),
):
    if client_id:
        await db.set_setting("QUICKBOOKS_CLIENT_ID", client_id)
    if client_secret:
        await db.set_setting("QUICKBOOKS_CLIENT_SECRET", client_secret)
    if refresh_token:
        await db.set_setting("QUICKBOOKS_REFRESH_TOKEN", refresh_token)
    if company_id:
        await db.set_setting("QUICKBOOKS_COMPANY_ID", company_id)
    await db.set_setting("QUICKBOOKS_ENV", qb_env)

    resp = RedirectResponse("/settings", status_code=302)
    _flash_to_cookie(resp, [{"message": "QuickBooks settings updated.", "category": "success"}])
    return resp


@app.post("/settings/quickbooks/test")
@require_auth
async def test_qb_connection(request: Request):
    try:
        from quickbooks_interaction import QuickBooksSession
        qb = QuickBooksSession()
        result = qb.query("SELECT Id FROM CompanyInfo")
        return JSONResponse({"status": "ok", "message": "QuickBooks connection successful."})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


@app.post("/settings/password")
@require_auth
async def update_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    session = request.state.session
    user = await db.verify_password(session["username"], current_password)
    if not user:
        resp = RedirectResponse("/settings", status_code=302)
        _flash_to_cookie(resp, [{"message": "Current password is incorrect.", "category": "error"}])
        return resp

    if new_password != confirm_password:
        resp = RedirectResponse("/settings", status_code=302)
        _flash_to_cookie(resp, [{"message": "New passwords do not match.", "category": "error"}])
        return resp

    if len(new_password) < 8:
        resp = RedirectResponse("/settings", status_code=302)
        _flash_to_cookie(resp, [{"message": "Password must be at least 8 characters.", "category": "error"}])
        return resp

    await db.change_password(session["user_id"], new_password)
    resp = RedirectResponse("/settings", status_code=302)
    _flash_to_cookie(resp, [{"message": "Password changed successfully.", "category": "success"}])
    return resp


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@app.get("/chat", response_class=HTMLResponse)
@require_auth
async def chat_page(request: Request):
    conversations = await db.get_conversations(request.state.session["user_id"])
    ctx = _ctx(request, request.state.session, {"conversations": conversations})
    resp = templates.TemplateResponse("chat.html", ctx)
    _set_session(resp, request.state.session)
    _clear_flash_cookie(resp)
    return resp


@app.post("/chat/conversations")
@require_auth
async def chat_create_conversation(request: Request):
    cid = await db.create_conversation(request.state.session["user_id"])
    conv = await db.get_conversation(cid, request.state.session["user_id"])
    return JSONResponse({"id": conv["id"], "title": conv["title"]})


@app.get("/chat/conversations/{conversation_id}/messages")
@require_auth
async def chat_get_messages(request: Request, conversation_id: int):
    conv = await db.get_conversation(conversation_id, request.state.session["user_id"])
    if not conv:
        return JSONResponse({"error": "Not found"}, status_code=404)
    messages = await db.get_chat_messages(conversation_id)
    return JSONResponse({"messages": messages, "title": conv["title"]})


@app.delete("/chat/conversations/{conversation_id}")
@require_auth
async def chat_delete_conversation(request: Request, conversation_id: int):
    await db.delete_conversation(conversation_id, request.state.session["user_id"])
    return JSONResponse({"status": "ok"})


@app.patch("/chat/conversations/{conversation_id}")
@require_auth
async def chat_rename_conversation(request: Request, conversation_id: int):
    body = await request.json()
    title = body.get("title", "").strip()
    if not title:
        return JSONResponse({"error": "Title required"}, status_code=400)
    await db.update_conversation_title(conversation_id, title)
    return JSONResponse({"status": "ok"})


@app.post("/chat/send")
@require_auth
async def chat_send(request: Request):
    body = await request.json()
    conversation_id = body.get("conversation_id")
    message = body.get("message", "").strip()
    if not conversation_id or not message:
        return JSONResponse({"error": "conversation_id and message required"}, status_code=400)

    # Verify ownership
    conv = await db.get_conversation(conversation_id, request.state.session["user_id"])
    if not conv:
        return JSONResponse({"error": "Not found"}, status_code=404)

    # Save user message
    await db.add_chat_message(conversation_id, "user", message)
    await db.touch_conversation(conversation_id)

    async def event_stream():
        try:
            import anthropic

            # Get API key from scheduler config
            config = await db.get_scheduler_config()
            api_key = config.get("anthropic_api_key") if config else None
            if not api_key:
                yield f"data: {json.dumps({'type': 'error', 'content': 'No Anthropic API key configured. Go to Scheduler settings to add one.'})}\n\n"
                return

            client = anthropic.AsyncAnthropic(api_key=api_key)
            is_first_response = conv["title"] == "New Conversation"

            while True:
                # Build messages from DB
                db_messages = await db.get_chat_messages(conversation_id)
                api_messages = _build_api_messages(db_messages)

                # Stream response from Claude
                full_text = ""
                tool_calls = []

                async with client.messages.stream(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=CHAT_SYSTEM_PROMPT,
                    messages=api_messages,
                    tools=CHAT_TOOLS,
                ) as stream:
                    async for event in stream:
                        if event.type == "content_block_start":
                            if event.content_block.type == "tool_use":
                                tool_calls.append({
                                    "id": event.content_block.id,
                                    "name": event.content_block.name,
                                    "input_json": "",
                                })
                                yield f"data: {json.dumps({'type': 'tool_start', 'name': event.content_block.name, 'tool_call_id': event.content_block.id})}\n\n"

                        elif event.type == "content_block_delta":
                            if event.delta.type == "text_delta":
                                full_text += event.delta.text
                                yield f"data: {json.dumps({'type': 'text', 'content': event.delta.text})}\n\n"
                            elif event.delta.type == "input_json_delta":
                                if tool_calls:
                                    tool_calls[-1]["input_json"] += event.delta.partial_json

                    final_message = await stream.get_final_message()

                # Auto-title from first response
                if is_first_response and full_text:
                    title = full_text[:50].split("\n")[0]
                    if len(full_text) > 50:
                        title += "..."
                    await db.update_conversation_title(conversation_id, title)
                    yield f"data: {json.dumps({'type': 'title_update', 'title': title})}\n\n"
                    is_first_response = False

                # If no tool calls, save assistant message and finish
                if final_message.stop_reason != "tool_use":
                    if full_text:
                        await db.add_chat_message(conversation_id, "assistant", full_text)
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    return

                # Save text that came before tool calls (must precede tool_call rows in DB)
                if full_text:
                    await db.add_chat_message(conversation_id, "assistant", full_text)
                    full_text = ""

                # Handle tool calls: save them, execute, save results, then loop
                for tc in tool_calls:
                    tool_input = json.loads(tc["input_json"]) if tc["input_json"] else {}
                    await db.add_chat_message(
                        conversation_id, "tool_call",
                        json.dumps(tool_input),
                        tool_name=tc["name"], tool_call_id=tc["id"]
                    )

                    # Execute tool
                    result = await _execute_tool_async(tc["name"], tool_input)
                    await db.add_chat_message(
                        conversation_id, "tool_result",
                        result,
                        tool_name=tc["name"], tool_call_id=tc["id"]
                    )
                    yield f"data: {json.dumps({'type': 'tool_result', 'name': tc['name'], 'tool_call_id': tc['id'], 'content': result})}\n\n"

                # Loop continues — will re-call Claude with tool results

        except Exception as e:
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
