import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def migration(name):
    path = Path(__file__).resolve().parents[1] / 'migrations' / 'versions' / name
    spec = importlib.util.spec_from_file_location('profile_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_profile_migration_preserves_roster_and_accepts_unknowns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite3'}")
    metadata = MetaData()
    Table('jockeys', metadata, Column('id', Integer, primary_key=True))
    metadata.create_all(engine)
    old = migration('20261008_0027_jockey_affiliation_snapshots.py')
    new = migration('20261009_0030_jockey_profile_fields.py')
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            old.upgrade()
        conn.execute(text('insert into jockeys (id) values (1)'))
        conn.execute(text('''insert into jockey_affiliation_snapshots
            (jockey_id,observed_on,meet_code,official_name_ko,observed_at_ms,
             source_url,source_sha256,api_source_url,api_sha256)
            values (1,'2026-10-08',1,'테스트기수',1,'https://race.kra.co.kr/',
                    :sha,'https://apis.data.go.kr/',:sha)'''), {'sha': 'a' * 64})
        with Operations.context(MigrationContext.configure(conn)):
            new.upgrade()
        row = conn.execute(text('select * from jockey_affiliation_snapshots')).mappings().one()
        assert row['official_name_ko'] == '테스트기수'
        assert row['debut_date'] is None
        assert row['riding_weight_own_kg'] is None
        conn.execute(text('''update jockey_affiliation_snapshots set
            debut_date='2001-07-06',riding_weight_own_kg=52.5,riding_weight_other_kg=53'''))
    with engine.begin() as conn:
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(text('update jockey_affiliation_snapshots set riding_weight_own_kg=0'))
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(text("update jockey_affiliation_snapshots set debut_date='1800-01-01'"))
        with Operations.context(MigrationContext.configure(conn)):
            new.downgrade()
        assert 'debut_date' not in {col['name'] for col in inspect(conn).get_columns(
            'jockey_affiliation_snapshots',
        )}
        assert conn.scalar(text('select count(*) from jockey_affiliation_snapshots')) == 1
    engine.dispose()
