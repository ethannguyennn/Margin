"""Opt-in live Tiger probe; disabled until the team supplies database access."""
import asyncio
import os
import sys

import pytest

from specs_relay import db

LIVE = pytest.mark.skipif(os.environ.get('SPECS_TEST_V2_DATABASE') != '1',
                          reason='live database test; set SPECS_TEST_V2_DATABASE=1 and DATABASE_URL')


def run(coro):
    # psycopg's async mode cannot use Windows' default Proactor loop (same as db/seed.py).
    return asyncio.run(coro, **({'loop_factory': asyncio.SelectorEventLoop} if sys.platform == 'win32' else {}))


@LIVE
def test_migration_twice_preserves_v1_and_deduplicates_null_and_step_progress():
    run(_migration_twice())


async def _migration_twice():
    try:
        await db.init_pool()
        report = await db.validate_v2_migration()
        assert report['before'] == report['after_first'] == report['after_second'] == {'documents': 1, 'chunks': 1}
        assert report['progress'] == {'rows': 2, 'task_rows': 1}
        assert report['progress_hypertable']
    finally:
        await db.close_pool()


@LIVE
def test_next_assignment_redelivers_a_lost_task_until_the_lens_acts_on_it():
    run(_redelivery())


async def _redelivery():
    tag = os.urandom(4).hex()
    dev, doc = f'LNS-T{tag}', f'SOP-T{tag}'
    try:
        await db.init_pool()
        await db.apply_migrations()
        async with db.pool().connection() as conn:
            await conn.execute("INSERT INTO documents(doc_id, revision, title, status) VALUES (%s, 'A', 'redelivery test', 'effective')", (doc,))
            await conn.execute("INSERT INTO devices(device_id, token_sha256) VALUES (%s, %s)", (dev, 'sha-' + tag))
            for asn, assigned in ((f'A1-{tag}', "now() - interval '1 minute'"), (f'A2-{tag}', "now() - interval '13 hours'")):
                await conn.execute(f"INSERT INTO assignments(assignment_id, device_id, doc_id, revision, assigned_at) VALUES (%s, %s, %s, 'A', {assigned})", (asn, dev, doc))
            await conn.execute("UPDATE assignments SET delivered_at = now() - interval '1 hour' WHERE assignment_id = %s", (f'A2-{tag}',))

        async def age_delivery(asn):
            async with db.pool().connection() as conn:
                await conn.execute("UPDATE assignments SET delivered_at = now() - interval '1 minute' WHERE assignment_id = %s", (asn,))

        first = await db.next_assignment(dev)
        assert first and first['assignment_id'] == f'A1-{tag}'  # A2 is past the lens's 12 h TTL: never re-sent
        assert await db.next_assignment(dev) is None, 'not re-sent while the lens may still be processing it'
        await age_delivery(f'A1-{tag}')
        again = await db.next_assignment(dev)
        assert again and again['assignment_id'] == f'A1-{tag}', 'a lost response is recovered'
        assert await db.insert_progress([{'assignment_id': f'A1-{tag}', 'step_id': None, 'kind': 'task_started',
                                          'ts': 1792280000000}], device_id=dev) == 1
        await age_delivery(f'A1-{tag}')
        assert await db.next_assignment(dev) is None, 'acted on: never handed out again'
    finally:
        if db._pool is not None:
            async with db.pool().connection() as conn:
                await conn.execute("DELETE FROM progress WHERE assignment_id LIKE %s", (f'%-{tag}',))
                await conn.execute("DELETE FROM assignments WHERE device_id = %s", (dev,))
                await conn.execute("DELETE FROM devices WHERE device_id = %s", (dev,))
                await conn.execute("DELETE FROM documents WHERE doc_id = %s", (doc,))
        await db.close_pool()


@LIVE
def test_ask_events_record_the_assignment_id():
    run(_event_assignment())


async def _event_assignment():
    trace = 'trace-' + os.urandom(4).hex()
    try:
        await db.init_pool()
        await db.apply_migrations()
        await db.write_event(None, trace, 'command', 'command', [], 'next', {'total': 1}, assignment_id='ASN-LIVE')
        rows = await db._rows('SELECT assignment_id FROM events WHERE trace_id = %s', (trace,))
        assert rows == [{'assignment_id': 'ASN-LIVE'}]
    finally:
        if db._pool is not None:
            async with db.pool().connection() as conn:
                await conn.execute('DELETE FROM events WHERE trace_id = %s', (trace,))
        await db.close_pool()
