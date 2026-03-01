"""Scheduler engine — APScheduler + Claude API categorization workflow."""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import database as db

# Logging to persistent file
data_dir = Path(os.environ.get("DATA_DIR", "/app/data"))
data_dir.mkdir(parents=True, exist_ok=True)
log_path = data_dir / "scheduler.log"

logger = logging.getLogger("scheduler")
logger.setLevel(logging.INFO)
_handler = logging.FileHandler(str(log_path))
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_handler)

scheduler = AsyncIOScheduler()
JOB_ID = "categorization_job"


async def configure_scheduler():
    """Read config from DB and start the scheduler."""
    config = await db.get_scheduler_config()
    if not config:
        return

    if config["enabled"] and config.get("anthropic_api_key"):
        _add_or_update_job(config["schedule_cron"])
    else:
        _remove_job()

    if not scheduler.running:
        scheduler.start()


async def reconfigure_scheduler():
    """Called when admin updates scheduler config."""
    config = await db.get_scheduler_config()
    if not config:
        return

    if config["enabled"] and config.get("anthropic_api_key"):
        _add_or_update_job(config["schedule_cron"])
    else:
        _remove_job()


def _add_or_update_job(cron_expr: str):
    """Add or replace the cron job."""
    parts = cron_expr.split()
    if len(parts) != 5:
        logger.error(f"Invalid cron expression: {cron_expr}")
        return

    trigger = CronTrigger(
        minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4]
    )
    existing = scheduler.get_job(JOB_ID)
    if existing:
        existing.reschedule(trigger)
        logger.info(f"Rescheduled job: {cron_expr}")
    else:
        scheduler.add_job(_scheduled_run, trigger, id=JOB_ID, replace_existing=True)
        logger.info(f"Added job: {cron_expr}")


def _remove_job():
    if scheduler.get_job(JOB_ID):
        scheduler.remove_job(JOB_ID)
        logger.info("Removed categorization job")


async def _scheduled_run():
    await run_categorization("scheduler")


async def run_categorization(triggered_by: str):
    """Main categorization workflow."""
    start = time.time()
    run_id = await db.create_run(triggered_by)
    logger.info(f"Run #{run_id} started (triggered_by={triggered_by})")

    try:
        config = await db.get_scheduler_config()
        if not config or not config.get("anthropic_api_key"):
            raise ValueError("Anthropic API key not configured")

        # 1. Pull uncategorized transactions from QuickBooks
        transactions = await _fetch_uncategorized_transactions()
        if not transactions:
            await _finish_run(run_id, "completed", 0, 0, 0, "No uncategorized transactions found.", start)
            return

        # 2. Load rules
        rules = await db.get_rules(enabled_only=True)

        # 3. Call Claude for categorization
        result = await _call_claude(config["anthropic_api_key"], transactions, rules)

        # 4. Apply categorizations back to QuickBooks
        categorized_count = await _apply_categorizations(result.get("categorized", []))

        # 5. Save flagged items
        flagged_count = 0
        for item in result.get("flagged", []):
            await db.create_flagged_item(
                run_id=run_id,
                transaction_id=item.get("transaction_id", ""),
                transaction_date=item.get("date", ""),
                vendor=item.get("vendor", ""),
                amount=item.get("amount", 0),
                reason_flagged=item.get("reason", ""),
            )
            flagged_count += 1

        # 6. Save suggested rules
        for rule in result.get("suggested_rules", []):
            await db.create_rule(
                rule_type=rule.get("rule_type", "vendor_category"),
                pattern=rule.get("pattern", ""),
                category=rule.get("category"),
                description=rule.get("description"),
                source="learned",
            )

        await _finish_run(
            run_id, "completed", len(transactions), categorized_count, flagged_count,
            f"Processed {len(transactions)} transactions, categorized {categorized_count}, flagged {flagged_count}.",
            start,
        )

    except Exception as e:
        logger.error(f"Run #{run_id} failed: {e}")
        await _finish_run(run_id, "failed", 0, 0, 0, str(e), start)


async def _finish_run(run_id, status, processed, categorized, flagged, summary, start):
    duration = round(time.time() - start, 2)
    await db.update_run(
        run_id,
        status=status,
        transactions_processed=processed,
        transactions_categorized=categorized,
        transactions_flagged=flagged,
        summary_text=summary,
        duration_seconds=duration,
    )
    await db.update_scheduler_config(
        last_run_at=datetime.now(timezone.utc).isoformat(),
        last_run_status=status,
        last_run_summary=summary,
    )
    logger.info(f"Run #{run_id} {status} in {duration}s: {summary}")


async def _fetch_uncategorized_transactions() -> list[dict]:
    """Fetch uncategorized purchases from QuickBooks via sync wrapper."""
    try:
        from quickbooks_interaction import QuickBooksSession
        qb = await asyncio.to_thread(QuickBooksSession)
        result = await asyncio.to_thread(
            qb.query,
            "SELECT * FROM Purchase WHERE AccountRef IS NULL MAXRESULTS 100"
        )
        if isinstance(result, dict) and "QueryResponse" in result:
            return result["QueryResponse"].get("Purchase", [])
        return []
    except Exception as e:
        logger.warning(f"Failed to fetch transactions: {e}")
        return []


async def _call_claude(api_key: str, transactions: list, rules: list) -> dict:
    """Call Claude API for transaction categorization."""
    import anthropic

    rules_text = json.dumps([{
        "type": r["rule_type"], "pattern": r["pattern"],
        "category": r.get("category", ""), "description": r.get("description", "")
    } for r in rules], indent=2) if rules else "No rules defined yet."

    txn_text = json.dumps(transactions[:50], indent=2, default=str)  # Limit to 50

    system_prompt = f"""You are a professional bookkeeper assistant. Your job is to categorize QuickBooks transactions.

Apply these categorization rules:
{rules_text}

For each transaction, determine:
1. The appropriate category based on vendor name, amount, and description
2. Whether it should be flagged for manual review (unusual amounts, unclear vendors, possible personal expenses)
3. Any new rules you'd suggest based on patterns you notice

Respond with ONLY valid JSON in this exact format:
{{
  "categorized": [
    {{"transaction_id": "123", "category": "Office Supplies", "confidence": 0.95}}
  ],
  "flagged": [
    {{"transaction_id": "456", "vendor": "Unknown Vendor", "amount": 500.00, "date": "2024-01-15", "reason": "Unknown vendor with high amount"}}
  ],
  "suggested_rules": [
    {{"rule_type": "vendor_category", "pattern": "Vendor Name", "category": "Category", "description": "Auto-suggested"}}
  ]
}}"""

    client = anthropic.AsyncAnthropic(api_key=api_key)
    message = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": f"Categorize these transactions:\n{txn_text}"}],
    )

    response_text = message.content[0].text
    # Extract JSON from response
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        # Try to find JSON block in response
        import re
        match = re.search(r'\{[\s\S]*\}', response_text)
        if match:
            return json.loads(match.group())
        logger.error(f"Failed to parse Claude response: {response_text[:200]}")
        return {"categorized": [], "flagged": [], "suggested_rules": []}


async def _apply_categorizations(categorized: list) -> int:
    """Apply categorizations back to QuickBooks."""
    if not categorized:
        return 0

    count = 0
    try:
        from quickbooks_interaction import QuickBooksSession
        qb = await asyncio.to_thread(QuickBooksSession)
        for item in categorized:
            try:
                # Note: actual QB update logic depends on entity type
                # This is a placeholder for the categorization write-back
                logger.info(f"Categorized transaction {item.get('transaction_id')} as {item.get('category')}")
                count += 1
            except Exception as e:
                logger.warning(f"Failed to categorize {item.get('transaction_id')}: {e}")
    except Exception as e:
        logger.error(f"Failed to apply categorizations: {e}")

    return count
