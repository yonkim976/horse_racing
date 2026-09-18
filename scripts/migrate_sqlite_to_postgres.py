#!/usr/bin/env python3
"""Stream the immutable SQLite snapshot into an empty Supabase PostgreSQL schema."""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql
from sqlalchemy import BigInteger, Boolean, Float, Integer, String

from horse_racing.db import models  # noqa: F401
from horse_racing.db.base import Base

DEFAULT_SOURCE = Path("data/backups/after_historical_backfill_20260918.sqlite3")
DEFAULT_SOURCE_SHA256 = "79708446f6aea3840c01589906c0c3e4d9ec744d94fc22b82c9edc83ce3dc322"
DEFAULT_URL_ENV = "SUPABASE_DB_URL"


def _postgres_dsn(value: str) -> str:
    """Accept either a PostgreSQL URI or SQLAlchemy's postgresql+psycopg URI."""
    parts = urlsplit(value)
    if parts.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise ValueError("target URL must use postgres:// or postgresql://")
    scheme = "postgresql" if parts.scheme == "postgresql+psycopg" else parts.scheme
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


def _source_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _table_count_sqlite(connection: sqlite3.Connection, table_name: str) -> int:
    quoted = table_name.replace('"', '""')
    return int(connection.execute(f'SELECT count(*) FROM "{quoted}"').fetchone()[0])


def _table_count_postgres(connection: psycopg.Connection, schema: str, table: str) -> int:
    query = sql.SQL("SELECT count(*) FROM {}.{}").format(
        sql.Identifier(schema), sql.Identifier(table)
    )
    return int(connection.execute(query).fetchone()[0])


def _partial_target_resume_id(
    source: sqlite3.Connection,
    target: psycopg.Connection,
    *,
    schema: str,
    table_name: str,
    target_count: int,
) -> int | None:
    """Return the last copied id after proving the target is a source-id prefix."""
    target_bounds_query = sql.SQL("SELECT min(id), max(id) FROM {}.{}").format(
        sql.Identifier(schema), sql.Identifier(table_name)
    )
    target_min, target_max = target.execute(target_bounds_query).fetchone()
    if target_min is None or target_max is None:
        raise RuntimeError(
            f"{schema}.{table_name} has {target_count:,} rows but no id bounds"
        )

    quoted_table = table_name.replace('"', '""')
    source_min, source_prefix_count = source.execute(
        f'SELECT min(id), count(*) FROM "{quoted_table}" WHERE id <= ?',
        (target_max,),
    ).fetchone()
    if target_min != source_min or target_count != source_prefix_count:
        raise RuntimeError(
            f"{schema}.{table_name} has a non-prefix partial load: "
            f"target_count={target_count:,}, target_id_range={target_min}..{target_max}, "
            f"source_prefix_count={source_prefix_count:,}"
        )
    return int(target_max)


def _source_columns(connection: sqlite3.Connection) -> dict[str, set[str]]:
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    result: dict[str, set[str]] = {}
    for (table_name,) in tables:
        quoted_table = str(table_name).replace('"', '""')
        result[str(table_name)] = {
            str(row[1])
            for row in connection.execute(f'PRAGMA table_info("{quoted_table}")').fetchall()
        }
    return result


def _validate_source_string_lengths(connection: sqlite3.Connection) -> None:
    problems = []
    source_columns = _source_columns(connection)
    for table in Base.metadata.sorted_tables:
        if table.name not in source_columns:
            continue
        quoted_table = table.name.replace('"', '""')
        for column in table.columns:
            if column.name not in source_columns[table.name]:
                continue
            if not isinstance(column.type, String) or column.type.length is None:
                continue
            quoted_column = column.name.replace('"', '""')
            actual_max = int(
                connection.execute(
                    f'SELECT coalesce(max(length("{quoted_column}")), 0) '
                    f'FROM "{quoted_table}"'
                ).fetchone()[0]
            )
            if actual_max > column.type.length:
                problems.append(
                    f"{table.name}.{column.name}: declared={column.type.length}, "
                    f"actual_max={actual_max}"
                )
    if problems:
        raise RuntimeError("source string length violations: " + "; ".join(problems))


def _validate_source_integer_ranges(connection: sqlite3.Connection) -> None:
    minimum = -(2**31)
    maximum = 2**31 - 1
    problems = []
    source_columns = _source_columns(connection)
    for table in Base.metadata.sorted_tables:
        if table.name not in source_columns:
            continue
        columns = [
            column
            for column in table.columns
            if column.name in source_columns[table.name]
            if isinstance(column.type, Integer)
            and not isinstance(column.type, (BigInteger, Boolean))
        ]
        if not columns:
            continue
        quoted_table = table.name.replace('"', '""')
        expressions = []
        for column in columns:
            quoted_column = column.name.replace('"', '""')
            expressions.extend(
                (
                    f'min(CAST("{quoted_column}" AS INTEGER))',
                    f'max(CAST("{quoted_column}" AS INTEGER))',
                )
            )
        row = connection.execute(
            f'SELECT {", ".join(expressions)} FROM "{quoted_table}"'
        ).fetchone()
        for index, column in enumerate(columns):
            actual_min = row[index * 2]
            actual_max = row[index * 2 + 1]
            if actual_min is not None and (
                actual_min < minimum or actual_max > maximum
            ):
                problems.append(
                    f"{table.name}.{column.name}: min={actual_min}, max={actual_max}"
                )
    if problems:
        raise RuntimeError("source integer range violations: " + "; ".join(problems))


def _validate_source_numeric_types(connection: sqlite3.Connection) -> None:
    problems = []
    source_columns = _source_columns(connection)
    for table in Base.metadata.sorted_tables:
        if table.name not in source_columns:
            continue
        numeric_columns = []
        for column in table.columns:
            if column.name not in source_columns[table.name]:
                continue
            if isinstance(column.type, Boolean):
                numeric_columns.append((column, ("integer",)))
            elif isinstance(column.type, Integer):
                numeric_columns.append((column, ("integer",)))
            elif isinstance(column.type, Float):
                numeric_columns.append((column, ("integer", "real")))
        if not numeric_columns:
            continue
        quoted_table = table.name.replace('"', '""')
        expressions = []
        for column, allowed_types in numeric_columns:
            quoted_column = column.name.replace('"', '""')
            allowed_sql = ", ".join(f"'{value}'" for value in allowed_types)
            expressions.append(
                f'sum(CASE WHEN "{quoted_column}" IS NOT NULL '
                f'AND typeof("{quoted_column}") NOT IN ({allowed_sql}) '
                "THEN 1 ELSE 0 END)"
            )
        counts = connection.execute(
            f'SELECT {", ".join(expressions)} FROM "{quoted_table}"'
        ).fetchone()
        for index, (column, allowed_types) in enumerate(numeric_columns):
            invalid_count = int(counts[index] or 0)
            if not invalid_count:
                continue
            quoted_column = column.name.replace('"', '""')
            allowed_sql = ", ".join(f"'{value}'" for value in allowed_types)
            samples = connection.execute(
                f'SELECT DISTINCT CAST("{quoted_column}" AS TEXT), '
                f'typeof("{quoted_column}") FROM "{quoted_table}" '
                f'WHERE "{quoted_column}" IS NOT NULL '
                f'AND typeof("{quoted_column}") NOT IN ({allowed_sql}) LIMIT 5'
            ).fetchall()
            problems.append(
                f"{table.name}.{column.name}: count={invalid_count}, samples={samples}"
            )
    if problems:
        raise RuntimeError("source numeric type violations: " + "; ".join(problems))


def _validate_target_schema(connection: psycopg.Connection, schema: str) -> None:
    expected = {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.tables.values()
    }
    rows = connection.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = %s
        """,
        (schema,),
    ).fetchall()
    actual: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        actual.setdefault(table_name, set()).add(column_name)
    problems = []
    for table_name, columns in expected.items():
        if table_name not in actual:
            problems.append(f"missing table {schema}.{table_name}")
        elif actual[table_name] != columns:
            missing = sorted(columns - actual[table_name])
            extra = sorted(actual[table_name] - columns)
            problems.append(f"{table_name}: missing={missing}, extra={extra}")
    if problems:
        raise RuntimeError("target schema mismatch: " + "; ".join(problems))


def _copy_table(
    source: sqlite3.Connection,
    target: psycopg.Connection,
    *,
    schema: str,
    table,
    source_count: int,
    target_count: int,
    batch_size: int,
    commit_size: int,
) -> None:
    columns = list(table.columns)
    names = [column.name for column in columns]
    bool_positions = {
        index for index, column in enumerate(columns) if isinstance(column.type, Boolean)
    }
    resume_id = None
    if target_count:
        resume_id = _partial_target_resume_id(
            source,
            target,
            schema=schema,
            table_name=table.name,
            target_count=target_count,
        )
        print(
            f"  {table.name}: resume after id={resume_id} "
            f"({target_count:,}/{source_count:,} already committed)",
            flush=True,
        )

    source_query = "SELECT " + ", ".join(f'"{name}"' for name in names)
    source_query += f' FROM "{table.name}"'
    parameters: tuple[int, ...] = ()
    if resume_id is not None:
        source_query += " WHERE id > ?"
        parameters = (resume_id,)
    source_query += " ORDER BY id"
    copy_query = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
        sql.Identifier(schema),
        sql.Identifier(table.name),
        sql.SQL(", ").join(map(sql.Identifier, names)),
    )
    source_cursor = source.execute(source_query, parameters)
    copied = target_count
    started = time.monotonic()
    while copied < source_count:
        committed_before = copied
        with target.transaction():
            with target.cursor().copy(copy_query) as copy:
                while copied - committed_before < commit_size:
                    remaining = commit_size - (copied - committed_before)
                    rows = source_cursor.fetchmany(min(batch_size, remaining))
                    if not rows:
                        break
                    for row in rows:
                        values = list(row)
                        for position in bool_positions:
                            if values[position] is not None:
                                values[position] = bool(values[position])
                        copy.write_row(values)
                    copied += len(rows)
                    elapsed = max(time.monotonic() - started, 0.001)
                    if copied == source_count or copied % max(commit_size, 250_000) == 0:
                        print(
                            f"  {table.name}: {copied:,}/{source_count:,} "
                            f"({copied / elapsed:,.0f} rows/s)",
                            flush=True,
                        )
        if copied == committed_before:
            break
    if copied != source_count:
        raise RuntimeError(f"{table.name}: copied {copied}, expected {source_count}")


def _reset_sequence(connection: psycopg.Connection, schema: str, table_name: str) -> None:
    qualified = f'{schema}."{table_name}"'
    sequence = connection.execute(
        "SELECT pg_get_serial_sequence(%s, 'id')", (qualified,)
    ).fetchone()[0]
    if sequence is None:
        return
    max_query = sql.SQL("SELECT max(id) FROM {}.{}").format(
        sql.Identifier(schema), sql.Identifier(table_name)
    )
    max_id = connection.execute(max_query).fetchone()[0]
    if max_id is None:
        connection.execute("SELECT setval(%s, 1, false)", (sequence,))
    else:
        connection.execute("SELECT setval(%s, %s, true)", (sequence, max_id))


def migrate(
    source_path: Path,
    dsn: str,
    *,
    schema: str,
    batch_size: int,
    commit_size: int,
) -> None:
    tables = list(Base.metadata.sorted_tables)
    with _source_connection(source_path) as source:
        quick_check = source.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise RuntimeError(f"SQLite quick_check failed: {quick_check}")
        _validate_source_string_lengths(source)
        _validate_source_integer_ranges(source)
        _validate_source_numeric_types(source)

        source_counts = {
            table.name: _table_count_sqlite(source, table.name) for table in tables
        }
        print(
            f"source={source_path} tables={len(tables)} rows={sum(source_counts.values()):,}",
            flush=True,
        )

        with psycopg.connect(dsn, autocommit=True) as target:
            target.execute("SET statement_timeout = 0")
            target.execute("SET lock_timeout = '30s'")
            target.execute("SET wal_compression = on")
            _validate_target_schema(target, schema)

            for table in tables:
                source_count = source_counts[table.name]
                target_count = _table_count_postgres(target, schema, table.name)
                if target_count == source_count:
                    print(f"skip {table.name}: already complete ({source_count:,})", flush=True)
                    continue
                if target_count > source_count:
                    raise RuntimeError(
                        f"{schema}.{table.name} has {target_count:,}/{source_count:,} rows"
                    )
                print(
                    f"copy {table.name}: {source_count:,} rows "
                    f"({target_count:,} already committed)",
                    flush=True,
                )
                _copy_table(
                    source,
                    target,
                    schema=schema,
                    table=table,
                    source_count=source_count,
                    target_count=target_count,
                    batch_size=batch_size,
                    commit_size=commit_size,
                )
                loaded = _table_count_postgres(target, schema, table.name)
                if loaded != source_count:
                    raise RuntimeError(
                        f"{table.name}: target count {loaded}, expected {source_count}"
                    )
                _reset_sequence(target, schema, table.name)

            print("validating final row counts", flush=True)
            mismatches = []
            for table in tables:
                loaded = _table_count_postgres(target, schema, table.name)
                expected = source_counts[table.name]
                if loaded != expected:
                    mismatches.append(f"{table.name}: source={expected}, target={loaded}")
            if mismatches:
                raise RuntimeError("row-count validation failed: " + "; ".join(mismatches))
            print(f"migration complete: {sum(source_counts.values()):,} rows", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy the frozen SQLite snapshot to an already-migrated Supabase database."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--url-env", default=DEFAULT_URL_ENV)
    parser.add_argument("--schema", default="public")
    parser.add_argument("--batch-size", type=int, default=10_000)
    parser.add_argument("--commit-size", type=int, default=100_000)
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    if args.commit_size <= 0:
        parser.error("--commit-size must be positive")
    raw_url = os.environ.get(args.url_env)
    if not raw_url:
        print(f"missing environment variable: {args.url_env}", file=sys.stderr)
        raise SystemExit(2)
    try:
        expected_sha256 = args.expected_sha256
        if expected_sha256 is None and args.source == DEFAULT_SOURCE:
            expected_sha256 = DEFAULT_SOURCE_SHA256
        if expected_sha256 is not None:
            actual_sha256 = _sha256(args.source)
            if actual_sha256 != expected_sha256:
                raise RuntimeError(
                    f"source SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
                )
            print(f"source_sha256={actual_sha256}", flush=True)
        dsn = _postgres_dsn(raw_url)
        migrate(
            args.source,
            dsn,
            schema=args.schema,
            batch_size=args.batch_size,
            commit_size=args.commit_size,
        )
    except (OSError, RuntimeError, ValueError, psycopg.Error) as error:
        print(f"migration failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
