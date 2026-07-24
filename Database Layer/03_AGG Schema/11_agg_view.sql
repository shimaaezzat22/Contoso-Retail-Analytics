-- ============================================================================
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║                                                                          ║
-- ║   PROJECT    : Contoso Retail — End-to-End BI Analytics                 ║
-- ║   PROGRAMME  : DEPI — Data Analysis with Power BI Track                 ║
-- ║   AUTHOR     : Waleed Mouhammed                                          ║
-- ║   ENGINE     : SQL Server 2025 (T-SQL)                                   ║
-- ║   SCRIPT     : 11 — Aggregation Views ([agg] schema)                    ║
-- ║   VERSION    : 2.0 (Amended — single agg view)                          ║
-- ║   DATE       : June 2026                                                 ║
-- ║                                                                          ║
-- ╠══════════════════════════════════════════════════════════════════════════╣
-- ║                                                                          ║
-- ║  AMENDMENT LOG v1.x → v2.0                                              ║
-- ║                                                                          ║
-- ║  DECISION: agg.vStoreSalesDailySummary REMOVED entirely.                ║
-- ║                                                                          ║
-- ║  ROOT CAUSE                                                              ║
-- ║  dbo.FactSales (source of fact.vStoreSales) is already at its minimum   ║
-- ║  possible grain: one row per Product × Store × Date. There are no        ║
-- ║  repeated Product-Store-Date combinations to collapse. Every GROUP BY    ║
-- ║  permutation tried (with or without ChannelKey) returned exactly         ║
-- ║  3,406,089 rows — identical to the source. The table is pre-aggregated  ║
-- ║  at the source system level and cannot be compressed further.            ║
-- ║                                                                          ║
-- ║  ARCHITECTURAL CONSEQUENCE                                               ║
-- ║  fact.vStoreSales will remain DirectQuery in the Composite Model.        ║
-- ║  Since it is already at summary grain, DQ queries against it fire a      ║
-- ║  single efficient GROUP BY SQL query — the latency is acceptable and     ║
-- ║  no Import agg layer is needed or beneficial.                            ║
-- ║                                                                          ║
-- ║  SCOPE OF THIS SCRIPT (v2.0)                                             ║
-- ║  One view only:                                                          ║
-- ║    [agg].[vOnlineSalesDailySummary]  — fact.vOnlineSales (~13M rows)    ║
-- ║  Verified compression in v1.0: 12,627,608 rows → 557,271 agg rows       ║
-- ║  (22× compression ratio at daily grain — correct and expected).          ║
-- ║                                                                          ║
-- ╠══════════════════════════════════════════════════════════════════════════╣
-- ║                                                                          ║
-- ║  AGGREGATION GRAIN                                                       ║
-- ║  Daily: one row per DateKey × ProductKey × StoreKey                      ║
-- ║         × PromotionKey × CurrencyKey                                     ║
-- ║                                                                          ║
-- ║  POWER BI AGGREGATION ROUTING                                            ║
-- ║  Queries at day / product / store grain  →  Import agg  (<10ms)         ║
-- ║  Queries at customer / order / line grain →  DQ fact.vOnlineSales (SQL) ║
-- ║                                                                          ║
-- ║  PREREQUISITES                                                           ║
-- ║  Script 10 (10_fact_Views_v2.sql) must be complete.                     ║
-- ║  [fact].[vOnlineSales] must exist before running this script.            ║
-- ║                                                                          ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
-- ============================================================================

PRINT '';
PRINT '=============================================================================';
PRINT '  Script 11 v2.0 -- Aggregation Views ([agg] schema)';
PRINT '  Single view: agg.vOnlineSalesDailySummary';
PRINT '  fact.vStoreSales excluded -- already at minimum grain in source.';
PRINT '=============================================================================';
PRINT '';

USE ContosoRetailDW;

SET NOCOUNT ON;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

-- ============================================================================
-- SECTION 0 -- PRE-FLIGHT CHECK
-- ============================================================================

PRINT '  Running pre-flight check...';
GO

IF OBJECT_ID('[fact].[vOnlineSales]', 'V') IS NULL
BEGIN
    RAISERROR('FATAL: [fact].[vOnlineSales] not found. Run Script 10 first.', 16, 1);
    SET NOEXEC ON;
END
ELSE PRINT '  OK [fact].[vOnlineSales] confirmed.';
GO

PRINT '  OK Pre-check passed.';
PRINT '';
GO

SET NOEXEC OFF;
GO


-- ============================================================================
-- SECTION 1 -- CREATE [agg] SCHEMA
-- ============================================================================

PRINT '  Creating [agg] schema (if not exists)...';
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'agg')
BEGIN
    EXEC('CREATE SCHEMA [agg] AUTHORIZATION [dbo]');
    PRINT '  OK Schema [agg] created.';
END
ELSE
    PRINT '  OK Schema [agg] already exists -- skipped.';
GO

-- Drop the now-obsolete StoreSales agg view if it exists from a prior run.
IF OBJECT_ID('[agg].[vStoreSalesDailySummary]', 'V') IS NOT NULL
BEGIN
    DROP VIEW [agg].[vStoreSalesDailySummary];
    PRINT '  OK [agg].[vStoreSalesDailySummary] dropped (obsolete -- not needed).';
END
GO


-- ============================================================================
-- VIEW 1 -- agg.vOnlineSalesDailySummary
--
-- Source  : fact.vOnlineSales  (~12.6M rows)
-- Grain   : DateKey x ProductKey x StoreKey x PromotionKey x CurrencyKey
-- Result  : ~557,271 rows  (22x compression ratio -- verified in v1.0)
--
-- WHAT THIS AGG TABLE ANSWERS (routes to Import, zero SQL fired):
--   Total Revenue by day / month / year
--   Gross Profit by day / product category / store
--   Units sold by day / store / promotion
--   Return amounts by day / product / store
--   Any combination of date + product + store + promotion + currency slicers
--
-- WHAT FALLS THROUGH TO DQ fact.vOnlineSales (SQL fired):
--   Any filter or grouping on CustomerKey  (individual customer analytics)
--   Any filter or grouping on SalesOrderNumber  (order-level drill)
--   Any filter on SalesOrderLineNumber  (line-level drill)
--
-- POWER BI AGGREGATION MAPPING
-- Configure in: Home -> Transform data -> Manage aggregations
--   Column             Summarisation   Maps to DQ detail column
--   ─────────────────  ─────────────   ──────────────────────────────────────
--   SalesAmount        Sum             fact vOnlineSales[SalesAmount]
--   TotalCost          Sum             fact vOnlineSales[TotalCost]
--   GrossProfit        Sum             fact vOnlineSales[GrossProfit]
--   SalesQuantity      Sum             fact vOnlineSales[SalesQuantity]
--   ReturnAmount       Sum             fact vOnlineSales[ReturnAmount]
--   ReturnQuantity     Sum             fact vOnlineSales[ReturnQuantity]
--   DiscountAmount     Sum             fact vOnlineSales[DiscountAmount]
--   DiscountQuantity   Sum             fact vOnlineSales[DiscountQuantity]
--   OrderLineCount     Sum             fact vOnlineSales[OnlineSalesKey]
--   DateKey            GroupBy         dim vDate[DateKey]
--   ProductKey         GroupBy         dim vProduct[ProductKey]
--   StoreKey           GroupBy         dim vStore[StoreKey]
--   PromotionKey       GroupBy         dim vPromotion[PromotionKey]
--   CurrencyKey        GroupBy         dim vCurrency[CurrencyKey]
-- ============================================================================

PRINT '  Creating agg.vOnlineSalesDailySummary...';
GO

CREATE OR ALTER VIEW [agg].[vOnlineSalesDailySummary]
AS
SELECT
    -- ── AGGREGATION SPINE (GROUP-BY KEYS) ─────────────────────────────────
    -- DateKey is already shifted +16 years by fact.vOnlineSales.
    -- No re-shifting occurs here -- SELECT from the shifted view directly.
    fos.[DateKey],                               -- INT YYYYMMDD, FK -> dim.vDate
    MIN(fos.[OrderDate])        AS OrderDate,    -- DATE companion, display only

    fos.[ProductKey],                            -- FK -> dim.vProduct
    fos.[StoreKey],                              -- FK -> dim.vStore
    fos.[PromotionKey],                          -- FK -> dim.vPromotion
    fos.[CurrencyKey],                           -- FK -> dim.vCurrency

    -- ── ADDITIVE SUM MEASURES ─────────────────────────────────────────────
    -- All fully additive across every dimension -- safe to SUM at any grain.
    SUM(fos.[SalesAmount])      AS SalesAmount,
    SUM(fos.[TotalCost])        AS TotalCost,

    -- GrossProfit is pre-computed in fact.vOnlineSales as SalesAmount - TotalCost.
    -- Summing the pre-computed column avoids recalculating in DAX and ensures
    -- the agg value equals SUM(SalesAmount) - SUM(TotalCost) exactly.
    SUM(fos.[GrossProfit])      AS GrossProfit,

    SUM(fos.[SalesQuantity])    AS SalesQuantity,
    SUM(fos.[ReturnAmount])     AS ReturnAmount,
    SUM(fos.[ReturnQuantity])   AS ReturnQuantity,
    SUM(fos.[DiscountAmount])   AS DiscountAmount,
    SUM(fos.[DiscountQuantity]) AS DiscountQuantity,

    -- ── COUNT MEASURE ─────────────────────────────────────────────────────
    -- Transaction line volume proxy.
    -- Maps to fact vOnlineSales[OnlineSalesKey] with Summarisation = Count
    -- in the Power BI Manage Aggregations dialog.
    -- NOTE: This counts order LINES, not distinct orders.
    -- Distinct order count (COUNT DISTINCT SalesOrderNumber) is intentionally
    -- excluded -- COUNT DISTINCT cannot be safely pre-aggregated.
    COUNT(*)                    AS OrderLineCount

FROM [fact].[vOnlineSales] AS fos

GROUP BY
    fos.[DateKey],
    fos.[ProductKey],
    fos.[StoreKey],
    fos.[PromotionKey],
    fos.[CurrencyKey];
GO

PRINT '    OK agg.vOnlineSalesDailySummary created.';
GO


-- ============================================================================
-- SECTION 3 -- VERIFICATION QUERIES
-- Run all three checks. All must pass before proceeding to Phase 2.
-- ============================================================================

PRINT '';
PRINT '  Running verification queries...';
GO

-- ── CHECK 1: Row count and compression ratio ──────────────────────────────────
-- Expected:
--   fact.vOnlineSales (source) : ~12,627,608
--   agg.vOnlineSalesDailySummary (agg) : ~557,271  (22x compression)
-- If agg rows >= source rows: the GROUP BY grain is wrong.
SELECT
    'fact.vOnlineSales (source)'             AS [Table],
    FORMAT(COUNT(*), 'N0')                   AS [Row Count],
    '---'                                    AS [Compression Ratio]
FROM [fact].[vOnlineSales]
UNION ALL
SELECT
    'agg.vOnlineSalesDailySummary (agg)',
    FORMAT(COUNT(*), 'N0'),
    FORMAT(
        CAST((SELECT COUNT(*) FROM [fact].[vOnlineSales]) AS FLOAT)
        / NULLIF(COUNT(*), 0),
        'N1'
    ) + 'x'
FROM [agg].[vOnlineSalesDailySummary];
GO

-- ── CHECK 2: Date range and dimension cardinality ─────────────────────────────
-- Expected: Min Date ~2023-xx-xx, Max Date ~2025-xx-xx
-- Confirms +16 year shift is correctly inherited from fact.vOnlineSales.
SELECT
    MIN([OrderDate])             AS [Min OrderDate],
    MAX([OrderDate])             AS [Max OrderDate],
    COUNT(DISTINCT [DateKey])    AS [Distinct Days],
    COUNT(DISTINCT [ProductKey]) AS [Distinct Products],
    COUNT(DISTINCT [StoreKey])   AS [Distinct Stores],
    COUNT(DISTINCT [PromotionKey]) AS [Distinct Promotions]
FROM [agg].[vOnlineSalesDailySummary];
GO

-- ── CHECK 3: Measure totals must match source exactly ─────────────────────────
-- CRITICAL: SalesAmount, TotalCost and GrossProfit from the agg view must
-- equal the source fact. Any discrepancy = incorrect aggregation logic.
SELECT
    'SalesAmount'                             AS [Measure],
    FORMAT(SUM([SalesAmount]), 'N2')          AS [Source Total]
FROM [fact].[vOnlineSales]
UNION ALL
SELECT 'SalesAmount (agg)', FORMAT(SUM([SalesAmount]), 'N2')
FROM [agg].[vOnlineSalesDailySummary]
UNION ALL
SELECT 'TotalCost (source)', FORMAT(SUM([TotalCost]), 'N2')
FROM [fact].[vOnlineSales]
UNION ALL
SELECT 'TotalCost (agg)', FORMAT(SUM([TotalCost]), 'N2')
FROM [agg].[vOnlineSalesDailySummary]
UNION ALL
SELECT 'GrossProfit -- SalesAmount-TotalCost (source)',
       FORMAT(SUM([SalesAmount]) - SUM([TotalCost]), 'N2')
FROM [fact].[vOnlineSales]
UNION ALL
SELECT 'GrossProfit -- SUM(GrossProfit) (agg)',
       FORMAT(SUM([GrossProfit]), 'N2')
FROM [agg].[vOnlineSalesDailySummary];
GO

PRINT '';
PRINT '=============================================================================';
PRINT '  Script 11 v2.0 complete.';
PRINT '  Objects created:';
PRINT '    [agg] schema';
PRINT '    [agg].[vOnlineSalesDailySummary]';
PRINT '';
PRINT '  fact.vStoreSales: NO agg view -- already at minimum grain in source.';
PRINT '  It will remain DirectQuery in the Composite Model.';
PRINT '';
PRINT '  Next step: return to Claude once all 3 checks pass.';
PRINT '  Phase 2 will configure the Power BI Composite Model on localhost:53055.';
PRINT '=============================================================================';
GO