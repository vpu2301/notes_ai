-- Not reversible: which notes had been finalized is only recoverable from
-- `finalized_at`, and re-freezing them would re-introduce a lifecycle the
-- code no longer has. The 0009 CHECK is not restored either — a draft with
-- a historical `finalized_at` is now a valid row.
SELECT 1;
