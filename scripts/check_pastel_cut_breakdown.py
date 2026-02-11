from __future__ import annotations

import os
import sys

from sqlalchemy import func

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from models import db
from models.block import Block
from models.pre_expansion import PreExpansion
from models.production import CuttingProductionRecord


def main() -> None:
    app = create_app()
    with app.app_context():
        pre = (
            PreExpansion.query.filter_by(purpose="Block")
            .order_by(PreExpansion.end_time.desc())
            .first()
        )
        if not pre:
            print("No Block pre-expansion found")
            return

        blocks = Block.query.filter_by(pre_expansion_id=pre.id).all()
        block_ids = [b.id for b in blocks]

        print("PreExpansion:", pre.id, pre.batch_no)
        print("Blocks:", len(block_ids))

        if not block_ids:
            print("Rows: 0")
            return

        rows = (
            db.session.query(
                CuttingProductionRecord.block_number,
                CuttingProductionRecord.profile_code,
                func.coalesce(func.sum(CuttingProductionRecord.cornices_produced), 0).label(
                    "profiles_cut"
                ),
                func.coalesce(
                    func.sum(CuttingProductionRecord.total_cornices_damaged), 0
                ).label("damaged"),
            )
            .filter(CuttingProductionRecord.block_id.in_(block_ids))
            .group_by(CuttingProductionRecord.block_number, CuttingProductionRecord.profile_code)
            .order_by(
                CuttingProductionRecord.block_number.asc(),
                CuttingProductionRecord.profile_code.asc(),
            )
            .all()
        )

        print("Rows:", len(rows))
        for r in rows[:50]:
            print(r.block_number, r.profile_code, int(r.profiles_cut or 0), int(r.damaged or 0))


if __name__ == "__main__":
    main()
