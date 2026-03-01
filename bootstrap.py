"""First-run initialization: data directory, database, default rules."""

import json
import os
from pathlib import Path
from database import init_db, get_rules, import_rules


async def bootstrap():
    """Ensure data directory exists, init DB, load default rules if empty."""
    data_dir = Path(os.environ.get("DATA_DIR", "/app/data"))
    data_dir.mkdir(parents=True, exist_ok=True)

    await init_db()

    # Import default rules if the rules table is empty and rules.json exists
    existing_rules = await get_rules()
    if not existing_rules:
        rules_path = Path(__file__).parent / "rules.json"
        if rules_path.exists():
            with open(rules_path) as f:
                default_rules = json.load(f)
            await import_rules(default_rules)
