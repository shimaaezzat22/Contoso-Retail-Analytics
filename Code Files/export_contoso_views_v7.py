"""
=============================================================
 Contoso Retail BI — Semantic Layer Data Exporter  v7
 Optimized for Power Query / Power BI Performance
=============================================================
 v7 — Changes from v6 (Performance Overhaul):

  PERF 6  Bypassing the Python GIL (ThreadPool -> ProcessPool)
    Data extraction via PyODBC releases the GIL during network I/O, but 
    converting Pandas to PyArrow and compressing to Parquet (Snappy) are 
    heavily CPU-bound. ThreadPoolExecutor forced all workers to fight for 
    a single CPU core. Switched to ProcessPoolExecutor to fully utilize 
    multi-core native Windows architectures.

  PERF 7  Connection Isolation for Multiprocessing
    SQLAlchemy engines cannot be shared across process boundaries safely.
    Moved engine instantiation inside the worker function so each
    process maintains its own independent connection pool.

  PERF 8  PyODBC arraysize optimization via yield_per
    Added yield_per=CHUNK_SIZE to execution_options in the chunked stream. 
    This instructs the underlying PyODBC cursor to fetch rows in bulk 
    (arraysize) rather than row-by-row, drastically reducing network 
    round trips between SQL Server and the Python client.

 v6 — Changes from v5:

  FIX 1  SAWarning: Unrecognized server version info '17.0.1000.7'
    Root cause: SQL Server 2025 reports major version 17. SQLAlchemy's
    mssql dialect was written when SQL Server 2022 (v16) was the latest
    known release; it has no entry for v17 and emits a SAWarning on
    every engine.connect() call.
    Fix: warnings.filterwarnings("ignore", ..., SAWarning) placed
    BEFORE the first engine.connect() call — in module scope so it
    fires before generate_schema_dictionary() opens a connection.

  PERF 1  Adaptive export strategy — single-read vs chunked streaming
    v5 sent ALL 22 views through the chunked streaming path regardless
    of table size. Chunking adds a full loop-iteration overhead
    (cursor open → schema inference → DataFrame construction → PyArrow
    conversion → schema cast → write) for every 200K-row page, even
    when a table has 7 rows (e.g. dim.vPaymentMethod).

    v6 classifies each view into one of two strategies:

      SINGLE-READ  (views estimated < CHUNK_SIZE rows)
        pd.read_sql() with NO chunksize → one DataFrame → one Arrow
        table → one writer.write_table() → writer.close().
        Eliminates all per-chunk overhead. Used for all 11 dim views
        and tiny fact views (vExchangeRate, vMarketingSpend).

      CHUNKED-STREAM  (views estimated >= CHUNK_SIZE rows)
        Existing v5 logic: stream_results=True + chunksize iteration.
        Used only for the 9 fact views that actually need it.

    The SINGLE_READ_VIEWS set is the authoritative list. If you add a
    new large dim view in the future, remove it from that set.

  PERF 2  WITH (NOLOCK) on all SELECT queries
    SQL Server acquires shared (S) locks on every 8 KB data page it
    reads. For a 13-million-row export (fact.vOnlineSales ≈ 100K
    pages), this means 100K lock acquisitions and releases, each of
    which can block on any concurrent writer. WITH (NOLOCK) (= READ
    UNCOMMITTED isolation) bypasses the lock manager entirely for this
    read-only export workload. The tradeoff — dirty reads — is
    acceptable because:
      (a) The gen tables are static after Script 08 completes.
      (b) The dbo source tables are read-only for this project.
    Applied to all queries via get_query_for_view().

  PERF 3  pool_pre_ping disabled
    SQLAlchemy's pool_pre_ping=True (the library default) issues a
    lightweight SELECT 1 before handing a connection to the caller.
    That is one extra round-trip × 22 views × parallel workers.
    Disabled: we know the server is up, and connection errors are
    caught by the existing try/except in export_view_to_parquet().

  PERF 4  use_setinputsizes=False in connect_args
    By default SQLAlchemy calls cursor.setinputsizes() before binding
    any parameters — even for parameter-free SELECT * queries. The
    pyodbc driver still negotiates parameter metadata with SQL Server
    on every execute(). Passing use_setinputsizes=False disables this
    call, removing one server round-trip per query.

  PERF 5  datetime column detection guard
    chunk.select_dtypes(include=["datetime64[ns]"]) scanned ALL
    columns on EVERY chunk even for views that have no datetime
    columns at all (e.g. dim.vPaymentMethod). Added an upfront
    HAS_DATETIME_COLS set per view that is computed once from the
    first chunk and reused for every subsequent chunk.
=============================================================
"""

import os
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SAWarning

# ── FIX 1: silence the SQL Server 2025 version warning ──────────────────────
# Must be placed in module scope — BEFORE any engine.connect() is called.
# SQL Server 2025 reports version string '17.0.1000.7'. SQLAlchemy's mssql
# dialect only knows up to version 16 (SQL Server 2022) and emits SAWarning
# for any unrecognised major version. The warning is purely cosmetic — all
# dialect features work correctly with SQL Server 2025.
warnings.filterwarnings(
    "ignore",
    message=r".*Unrecognized server version info.*",
    category=SAWarning,
)

# ══════════════════════════════════════════════════════════
#  ⚙️  CONFIGURATION
# ══════════════════════════════════════════════════════════

SERVER       = r"localhost\SQLEXPRESS"
DATABASE     = "ContosoRetailDW"
WINDOWS_AUTH = True          # Set to False to use SQL Authentication
SQL_USER     = "username"          # Only used if WINDOWS_AUTH is False
SQL_PASSWORD = "password"          # Only used if WINDOWS_AUTH is False


OUTPUT_DIR = os.path.join(Path(__file__).parent, "Contoso Data Files")

CHUNK_SIZE   = 200_000       # Rows per chunk — safe for 8 GB RAM machines
MAX_WORKERS  = 4             # Parallel view exports

# ── PERF 1: views that fit in a single read (no chunked streaming) ───────────
# All 11 dim views are tiny-to-small. These 2 fact views are also monthly-grain
# (vExchangeRate: ~36 months × 10 currencies; vMarketingSpend: ~36 months × 7
# channels) and will never exceed a few thousand rows.
# For every view in this set, pd.read_sql() is called WITHOUT chunksize,
# producing one DataFrame → one Arrow Table → one writer.write_table() call.
SINGLE_READ_VIEWS = {
    # All dimension views
    ("dim", "vDate"),
    ("dim", "vCustomer"),
    ("dim", "vProduct"),
    ("dim", "vStore"),
    ("dim", "vPromotion"),
    ("dim", "vEmployee"),
    ("dim", "vPaymentMethod"),
    ("dim", "vAcquisitionChannel"),
    ("dim", "vCurrency"),
    ("dim", "vReturnReason"),
    ("dim", "vChannel"),
    # Tiny fact views
    ("fact", "vExchangeRate"),
    ("fact", "vMarketingSpend"),
}

# ══════════════════════════════════════════════════════════
#  📋  VIEW REGISTRY  (11 dim + 11 fact = 22 total)
# ══════════════════════════════════════════════════════════

VIEWS = [
    # ── Dimension views (11) ─────────────────────────────
    ("dim", "vDate"),
    ("dim", "vCustomer"),
    ("dim", "vProduct"),
    ("dim", "vStore"),
    ("dim", "vPromotion"),
    ("dim", "vEmployee"),
    ("dim", "vPaymentMethod"),
    ("dim", "vAcquisitionChannel"),
    ("dim", "vCurrency"),
    ("dim", "vReturnReason"),
    ("dim", "vChannel"),

    # ── Fact views (11) ──────────────────────────────────
    ("fact", "vOnlineSales"),
    ("fact", "vStoreSales"),
    ("fact", "vReturns"),
    ("fact", "vInventory"),
    ("fact", "vSalesQuota"),
    ("fact", "vExchangeRate"),
    ("fact", "vOrderFulfillment"),
    ("fact", "vCustomerSurvey"),
    ("fact", "vMarketingSpend"),
    ("fact", "vCustomerAcquisition"),
    ("fact", "vOrderPayment"),
]

# ══════════════════════════════════════════════════════════
#  🔌  ENGINE
# ══════════════════════════════════════════════════════════

def get_engine():
    conn_params = {
        "driver":                "ODBC Driver 18 for SQL Server",
        "TrustServerCertificate": "yes",
    }
    if WINDOWS_AUTH:
        conn_params["Trusted_Connection"] = "yes"

    conn_url = URL.create(
        drivername="mssql+pyodbc",
        username=SQL_USER     if not WINDOWS_AUTH else None,
        password=SQL_PASSWORD if not WINDOWS_AUTH else None,
        host=SERVER,
        database=DATABASE,
        query=conn_params,
    )
    return create_engine(
        conn_url,
        pool_size=MAX_WORKERS + 2,
        # PERF 3: skip the SELECT 1 ping before each connection checkout —
        # we know the server is running and errors are caught downstream.
        pool_pre_ping=False,
        # PERF 4: skip cursor.setinputsizes() for parameter-free SELECTs —
        # removes one server round-trip per query execution.
        connect_args={"use_setinputsizes": False},
    )

# ══════════════════════════════════════════════════════════
#  🛠️  QUERY BUILDER
# ══════════════════════════════════════════════════════════

def get_query_for_view(schema, view):
    """
    Returns the SQL query string for a given view.

    PERF 2: WITH (NOLOCK) is applied to every query.
    SQL Server acquires shared locks on each 8KB data page during a
    sequential scan. For large fact tables (vOnlineSales ≈ 100K pages)
    this generates ~100K lock acquisitions per export run. NOLOCK
    (READ UNCOMMITTED isolation) bypasses the lock manager entirely.
    Dirty reads are acceptable: all source and gen tables are static
    for this read-only export workload.
    """
    return f"SELECT * FROM [{schema}].[{view}] WITH (NOLOCK)"

# ══════════════════════════════════════════════════════════
#  🧠  SCHEMA DICTIONARY GENERATOR
# ══════════════════════════════════════════════════════════

def generate_schema_dictionary(engine, views, output_dir):
    """
    Queries INFORMATION_SCHEMA.COLUMNS for all exported views and
    writes SchemaDictionary.csv — the Power Query M type manifest.
    """
    print(" Generating Schema Dictionary mapping...")

    schemas    = "','".join(sorted({s for s, _ in views}))
    view_names = "','".join(sorted({v for _, v in views}))

    query = f"""
    SELECT
        TABLE_SCHEMA  AS SchemaName,
        TABLE_NAME    AS ViewName,
        COLUMN_NAME   AS ColumnName,
        DATA_TYPE     AS SqlDataType
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA IN ('{schemas}')
      AND TABLE_NAME   IN ('{view_names}')
    ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
    """

    M_TYPES = {
        "int":              "Int64.Type",
        "bigint":           "Int64.Type",
        "smallint":         "Int64.Type",
        "tinyint":          "Int64.Type",
        "varchar":          "type text",
        "nvarchar":         "type text",
        "char":             "type text",
        "nchar":            "type text",
        "datetime":         "type datetime",
        "datetime2":        "type datetime",
        "date":             "type date",
        "money":            "Currency.Type",
        "smallmoney":       "Currency.Type",
        "decimal":          "type number",
        "numeric":          "type number",
        "float":            "type number",
        "real":             "type number",
        "bit":              "type logical",
        "uniqueidentifier": "type text",
    }

    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn)

        df["FileName"] = df["SchemaName"] + "_" + df["ViewName"] + ".parquet"
        df["DataType"] = df["SqlDataType"].map(M_TYPES).fillna("type any")

        out  = df[["FileName", "ColumnName", "DataType", "SqlDataType"]]
        path = os.path.join(output_dir, "SchemaDictionary.csv")
        out.to_csv(path, index=False)
        print(f"  ✔ Schema Dictionary saved → {path}")
        print(f"    (Upload alongside Parquet files for Power Query consumption)\n")

    except Exception as exc:
        print(f"  ✘ Schema Dictionary FAILED: {str(exc)[:120]}\n")

# ══════════════════════════════════════════════════════════
#  🔧  ARROW HELPERS
# ══════════════════════════════════════════════════════════

def _make_nullable_schema(arrow_schema: pa.Schema) -> pa.Schema:
    """
    Returns a copy of arrow_schema with every field marked nullable=True.

    Required for fact.vReturns (and any other UNION ALL view with cross-
    channel NULL columns): pandas reads all-NULL integer columns as
    float64(NaN). The first chunk that has actual integer values comes
    back as int64, causing a schema-mismatch crash in ParquetWriter.
    Locking a nullable schema + casting every chunk with safe=False
    allows float64(NaN) → int64(null) coercion without error.
    """
    return pa.schema(
        [pa.field(f.name, f.type, nullable=True) for f in arrow_schema]
    )


def _fix_datetimes(df: pd.DataFrame, dt_cols: set) -> pd.DataFrame:
    """
    Downcasts datetime64[ns] → datetime64[us] for Parquet compatibility.
    PERF 5: dt_cols is computed once per view (from the first chunk) and
    passed in, avoiding a repeated select_dtypes() scan on every chunk.
    """
    for col in dt_cols:
        df[col] = df[col].astype("datetime64[us]")
    return df


def _df_to_arrow(df: pd.DataFrame, writer_schema: pa.Schema) -> pa.Table:
    """
    Converts a DataFrame to an Arrow Table cast to writer_schema.
    Falls back to column-by-column repair if the bulk cast fails.
    """
    table = pa.Table.from_pandas(df, preserve_index=False)
    try:
        return table.cast(writer_schema, safe=False)
    except pa.ArrowInvalid:
        # Column-by-column fallback: replace uncastable columns with nulls
        arrays = []
        for field in writer_schema:
            col = table.column(field.name)
            try:
                arrays.append(col.cast(field.type, safe=False))
            except pa.ArrowInvalid:
                arrays.append(pa.array([None] * len(col), type=field.type))
        return pa.table(
            {f.name: arr for f, arr in zip(writer_schema, arrays)},
            schema=writer_schema,
        )

# ══════════════════════════════════════════════════════════
#  🚀  CORE EXPORT FUNCTION
# ══════════════════════════════════════════════════════════

def export_view_to_parquet(schema, view, output_dir):
    """
    PERF 7: Engine is instantiated INSIDE the worker process. 
    SQLAlchemy engines and pyodbc connections are not safe to pickle 
    or share across ProcessPoolExecutor boundaries.
    """
    engine = get_engine()
    
    full_name  = f"[{schema}].[{view}]"
    file_path  = os.path.join(output_dir, f"{schema}_{view}.parquet")
    start_time = time.time()
    query      = get_query_for_view(schema, view)

    writer        = None
    writer_schema = None
    dt_cols       = None   # set of datetime column names — detected once
    total_rows    = 0

    try:
        # ── PERF 1: choose export strategy based on view size ────────────────
        if (schema, view) in SINGLE_READ_VIEWS:
            # ── SINGLE-READ PATH (dim views + tiny facts) ────────────────────
            # One round-trip, one DataFrame, one Arrow table.
            # No chunked loop overhead.
            with engine.connect() as conn:
                df = pd.read_sql(text(query), conn)

            if not df.empty:
                dt_cols = set(df.select_dtypes(include=["datetime64[ns]"]).columns)
                df = _fix_datetimes(df, dt_cols)
                table         = pa.Table.from_pandas(df, preserve_index=False)
                writer_schema = _make_nullable_schema(table.schema)
                writer        = pq.ParquetWriter(
                    file_path, writer_schema, compression="snappy"
                )
                writer.write_table(table.cast(writer_schema, safe=False))
                total_rows = len(df)

        else:
            # ── CHUNKED-STREAM PATH (large and medium fact views) ─────────────
            # Streams rows in CHUNK_SIZE batches to keep peak RAM bounded.
            # PERF 8: yield_per=CHUNK_SIZE added to force ODBC bulk cursor fetching.
            with engine.connect().execution_options(stream_results=True, yield_per=CHUNK_SIZE) as conn:
                for chunk in pd.read_sql(text(query), conn, chunksize=CHUNK_SIZE):
                    if chunk.empty:
                        continue

                    # PERF 5: detect datetime columns once from first chunk
                    if dt_cols is None:
                        dt_cols = set(
                            chunk.select_dtypes(include=["datetime64[ns]"]).columns
                        )
                    if dt_cols:
                        chunk = _fix_datetimes(chunk, dt_cols)

                    table = pa.Table.from_pandas(chunk, preserve_index=False)

                    # Lock a nullable writer schema from the first chunk
                    if writer is None:
                        writer_schema = _make_nullable_schema(table.schema)
                        writer = pq.ParquetWriter(
                            file_path, writer_schema, compression="snappy"
                        )

                    writer.write_table(_df_to_arrow(chunk, writer_schema))
                    total_rows += len(chunk)

        elapsed = time.time() - start_time
        size_mb = os.path.getsize(file_path) / (1024 * 1024) if total_rows > 0 else 0
        strategy = "single" if (schema, view) in SINGLE_READ_VIEWS else "stream"
        print(
            f"  ✔ {full_name:<35} | {total_rows:>10,} rows "
            f"| {size_mb:>7.2f} MB | {elapsed:>5.1f}s  [{strategy}]"
        )
        return {
            "view": full_name, "rows": total_rows,
            "mb": size_mb, "seconds": elapsed, "status": "OK",
        }

    except Exception as exc:
        print(f"  ✘ {full_name:<35} | FAILED: {str(exc)[:80]}...")
        return {
            "view": full_name, "rows": 0,
            "mb": 0, "seconds": 0, "status": f"ERROR: {exc}",
        }

    finally:
        # Always close the writer — even if an exception fired mid-loop —
        # to prevent corrupt partial files and OS file-handle leaks.
        if writer is not None:
            writer.close()
        # Clean up the local engine instance so connections return to the void
        engine.dispose()

# ══════════════════════════════════════════════════════════
#  🎬  ENTRY POINT
# ══════════════════════════════════════════════════════════

def main():
    print(f"\n{'='*70}")
    print(f" CONTOSO DATA EXPORTER V7 — PARQUET & SCHEMA OPTIMIZED")
    print(f"{'='*70}\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Need a temporary engine just for the schema dictionary in the main process
    setup_engine = get_engine()
    generate_schema_dictionary(setup_engine, VIEWS, OUTPUT_DIR)
    setup_engine.dispose()

    print(f" Starting parallel export  (Processes: {MAX_WORKERS})...\n")
    print(
        f"  {'View':<35}   {'Rows':>10}   {'MB':>7}   {'Time':>5}  Strategy"
    )
    print(f"  {'-'*68}")

    results = []
    # PERF 6: ProcessPoolExecutor replaces ThreadPoolExecutor for true CPU parallelism
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(export_view_to_parquet, s, v, OUTPUT_DIR): (s, v)
            for s, v in VIEWS
        }
        for future in as_completed(futures):
            results.append(future.result())

    ok_count   = sum(1 for r in results if r["status"] == "OK")
    total_rows = sum(r["rows"]    for r in results)
    total_time = sum(r["seconds"] for r in results)

    print(f"\n{'='*70}")
    print(f" COMPLETED : {ok_count}/{len(VIEWS)} views exported successfully")
    print(f" Total Rows: {total_rows:,}")
    print(f" Agg. Time : {total_time:.1f}s  (sum across parallel workers)")
    print(f" Output    : {OUTPUT_DIR}")

    failed = [r for r in results if r["status"] != "OK"]
    if failed:
        print(f"\n FAILED VIEWS ({len(failed)}):")
        for r in failed:
            print(f"   ✘ {r['view']} — {r['status']}")

    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()