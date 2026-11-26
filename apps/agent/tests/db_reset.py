import db


async def reset_db_globals() -> None:
    """Reset shared clients, tolerating close errors from clients bound to another test loop.

    terminate() drops the pool without scheduling on its dead loop, which close() would do."""
    try:
        await db.close_all()
    except RuntimeError:
        if db._pool is not None:
            db._pool.terminate()
        db._pool = None
        db._redis = None
