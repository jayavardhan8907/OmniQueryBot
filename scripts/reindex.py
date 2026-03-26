from __future__ import annotations

import logging
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from omniquery_bot.config import Settings
from omniquery_bot.knowledge_base import KnowledgeBase


def main() -> None:
    settings = Settings.from_env()
    settings.validate_for_indexing()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    kb = KnowledgeBase(settings)
    kb.setup()
    stats = kb.reindex()

    print("Knowledge base sync complete")
    print(f"files_seen={stats['files_seen']}")
    print(f"files_reindexed={stats['files_reindexed']}")
    print(f"files_removed={stats['files_removed']}")
    print(f"chunks_written={stats['chunks_written']}")


if __name__ == "__main__":
    main()
