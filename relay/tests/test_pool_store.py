from types import SimpleNamespace

from margin_relay.main import _PoolStore


def test_pool_store_calls_db_pool_function():
    # Part 5's db module exposes pool() as a function, not the pool itself.
    pool = object()
    retrieve = SimpleNamespace(PgStore=lambda p: SimpleNamespace(pool=p))
    store = _PoolStore(retrieve, SimpleNamespace(pool=lambda: pool))._store()
    assert store.pool is pool
