"""Seed benchmark/reference data and the prompt registry for the demo.

Seeds facets_sim.{provider_agreement, filing_rule, reimbursement_policy} and
app_config.prompt_registry. Consistent with the synthetic contracts in data/contracts/.

Run with: uv run python -m db.seed_reference
"""

import asyncio
import logging
from datetime import date

from agents.agent_rag import DEFAULT_PROMPTS
from config import get_settings
from db.database import Database

logger = logging.getLogger(__name__)

# (provider_npi, contract_id, state, lob, effective_date, terminate_date)
PROVIDER_AGREEMENTS: list[tuple[str, str, str, str, date, date | None]] = [
    ("1234567890", "C-TX-001", "TX", "Medicare", date(2023, 1, 1), None),
    ("1987654321", "C-NY-001", "NY", "Medicaid", date(2022, 3, 1), None),
]

# (state, lob, days_to_file)
FILING_RULES: list[tuple[str, str, int]] = [
    ("TX", "Medicare", 90),
    ("FL", "Medicare", 90),
    ("CA", "Medicare", 95),
    ("NY", "Medicaid", 90),
    ("TX", "Medicaid", 95),
]

# (state, lob, lesser_of_required, expected_pct_of_medicare)
REIMBURSEMENT_POLICIES: list[tuple[str, str, int, float]] = [
    ("TX", "Medicare", 1, 100.0),
    ("FL", "Medicare", 1, 100.0),
    ("CA", "Medicare", 1, 100.0),
    ("NY", "Medicaid", 1, 100.0),
    ("TX", "Medicaid", 1, 100.0),
]


async def seed() -> None:
    """Populate reference tables and the prompt registry."""
    settings = get_settings()
    db = Database(settings.sql_connection_string())
    await db.connect()
    try:
        for npi, contract_id, state, lob, eff, term in PROVIDER_AGREEMENTS:
            await db.execute(
                """
                MERGE facets_sim.provider_agreement AS t
                USING (SELECT ? AS provider_npi, ? AS contract_id, ? AS state) AS s
                    ON t.provider_npi = s.provider_npi
                   AND t.contract_id = s.contract_id
                   AND t.state = s.state
                WHEN MATCHED THEN UPDATE SET lob = ?, effective_date = ?, terminate_date = ?
                WHEN NOT MATCHED THEN INSERT
                    (provider_npi, contract_id, state, lob, effective_date, terminate_date)
                    VALUES (?, ?, ?, ?, ?, ?);
                """,
                (npi, contract_id, state, lob, eff, term, npi, contract_id, state, lob, eff, term),
            )

        for state, lob, days in FILING_RULES:
            await db.execute(
                """
                MERGE facets_sim.filing_rule AS t
                USING (SELECT ? AS state, ? AS lob) AS s
                    ON t.state = s.state AND t.lob = s.lob
                WHEN MATCHED THEN UPDATE SET days_to_file = ?
                WHEN NOT MATCHED THEN INSERT (state, lob, days_to_file) VALUES (?, ?, ?);
                """,
                (state, lob, days, state, lob, days),
            )

        for state, lob, lesser, pct in REIMBURSEMENT_POLICIES:
            await db.execute(
                """
                MERGE facets_sim.reimbursement_policy AS t
                USING (SELECT ? AS state, ? AS lob) AS s
                    ON t.state = s.state AND t.lob = s.lob
                WHEN MATCHED THEN UPDATE SET lesser_of_required = ?, expected_pct_of_medicare = ?
                WHEN NOT MATCHED THEN INSERT
                    (state, lob, lesser_of_required, expected_pct_of_medicare)
                    VALUES (?, ?, ?, ?);
                """,
                (state, lob, lesser, pct, state, lob, lesser, pct),
            )

        for name, text in DEFAULT_PROMPTS.items():
            await db.execute(
                """
                MERGE app_config.prompt_registry AS t
                USING (SELECT ? AS name) AS s ON t.name = s.name
                WHEN MATCHED THEN UPDATE SET prompt_text = ?, updated_at = SYSUTCDATETIME()
                WHEN NOT MATCHED THEN INSERT (name, prompt_text) VALUES (?, ?);
                """,
                (name, text, name, text),
            )
    finally:
        await db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed())
    logger.info("Seeded reference data and %d prompts", len(DEFAULT_PROMPTS))
