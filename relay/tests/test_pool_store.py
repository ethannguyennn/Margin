from types import SimpleNamespace

from margin_relay.main import _retrieval_store


def test_retrieval_store_uses_db_adapter_without_opening_a_pool():
    store = object()
    db = SimpleNamespace(RetrievalStore=lambda: store)
    assert _retrieval_store(db) is store


def test_retrieval_store_supports_db_modules_implementing_the_protocol():
    db = SimpleNamespace()
    assert _retrieval_store(db) is db
