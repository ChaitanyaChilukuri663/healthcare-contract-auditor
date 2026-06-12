"""Seed facets_sim.mpfs_fee from data/mpfs_2025.csv.

Run with: uv run python -m db.seed_mpfs
"""

import asyncio
import logging

import pandas as pd

from config import PROJECT_ROOT, get_settings
from db.database import Database

logger = logging.getLogger(__name__)

CSV_PATH = PROJECT_ROOT / "data" / "mpfs_2025.csv"

_MERGE_SQL = """
MERGE facets_sim.mpfs_fee AS target
USING (SELECT ? AS cpt_code, ? AS locality) AS source
    ON target.cpt_code = source.cpt_code AND target.locality = source.locality
WHEN MATCHED THEN UPDATE SET
    description = ?, conversion_factor = ?, rvu = ?, amount = ?
WHEN NOT MATCHED THEN INSERT
    (cpt_code, locality, description, conversion_factor, rvu, amount)
    VALUES (?, ?, ?, ?, ?, ?);
"""


async def seed() -> int:
    """Load the MPFS CSV into facets_sim.mpfs_fee; returns the row count."""
    settings = get_settings()
    frame = pd.read_csv(CSV_PATH, dtype={"cpt_code": str, "locality": str})
    records = frame.to_dict(orient="records")

    db = Database(settings.sql_connection_string())
    await db.connect()
    try:
        for row in records:
            cpt = str(row["cpt_code"])
            locality = str(row["locality"])
            description = str(row["description"])
            conversion_factor = float(row["conversion_factor"])
            rvu = float(row["rvu"])
            amount = float(row["amount"])
            await db.execute(
                _MERGE_SQL,
                (
                    cpt,
                    locality,
                    description,
                    conversion_factor,
                    rvu,
                    amount,
                    cpt,
                    locality,
                    description,
                    conversion_factor,
                    rvu,
                    amount,
                ),
            )
        return len(records)
    finally:
        await db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = asyncio.run(seed())
    logger.info("Seeded %d MPFS rows from %s", count, CSV_PATH)
