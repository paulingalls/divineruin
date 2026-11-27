import pytest
from acceptance.merchant_harness import GRIMJAW, SWORD, merchant_session, rows

import db


async def test_failed_gold_write_rolls_back_sale_without_events(
    reset_db_pool: str, caplog: pytest.LogCaptureFixture
) -> None:
    async with merchant_session() as sale:
        pool = await db.get_pool()
        before = await rows(sale.player_id)
        await pool.execute("""
            CREATE FUNCTION reject_sale_gold() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF EXISTS (
                    SELECT FROM player_inventory WHERE player_id=NEW.player_id AND item_id='shortsword_basic'
                ) THEN
                    RAISE EXCEPTION 'fixture expected inventory removal before gold write';
                END IF;
                RAISE check_violation USING MESSAGE = 'injected sale gold failure';
            END $$;
        """)
        try:
            await pool.execute(f"""
                CREATE TRIGGER reject_sale_gold BEFORE UPDATE ON players
                FOR EACH ROW WHEN (NEW.player_id = '{sale.player_id}'
                    AND OLD.data->'gold' IS DISTINCT FROM NEW.data->'gold')
                EXECUTE FUNCTION reject_sale_gold();
            """)
            receipt = await sale.sell(SWORD, GRIMJAW, 2)
            assert await rows(sale.player_id) == before
            assert not sale.publications
            assert receipt.is_error, receipt.output
            assert any(
                "injected sale gold failure" in str(record.exc_info[1]) for record in caplog.records if record.exc_info
            )
        finally:
            await pool.execute("DROP FUNCTION reject_sale_gold() CASCADE")
