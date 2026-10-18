"""Opt-in live Tiger probe; disabled until the team supplies database access."""
import os

import pytest

from specs_relay import db


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get('SPECS_TEST_V2_DATABASE') != '1', reason='Tiger validation deferred until team merge; set SPECS_TEST_V2_DATABASE=1 to opt in')
async def test_migration_twice_preserves_v1_and_deduplicates_null_and_step_progress():
    try:
        await db.init_pool()
        report = await db.validate_v2_migration()
        assert report['before'] == report['after_first'] == report['after_second'] == {'documents': 1, 'chunks': 1}
        assert report['progress'] == {'rows': 2, 'task_rows': 1}
        assert report['progress_hypertable']
    finally:
        await db.close_pool()
