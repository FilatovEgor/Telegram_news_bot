# Phase 4C — duplicate detection benchmark

The production matcher remains conservative by default:

1. canonical URL and content-hash matches are exact fast paths;
2. Python `SequenceMatcher` with the existing normalized-title implementation remains the final title decision;
3. duplicate pairs remain `PENDING` for human review.

Migration `0008_pg_trgm_title_index` enables PostgreSQL's `pg_trgm` extension and adds a GIN expression index on `lower(articles.title)`. The index is an experiment enabler; it does not change the default matching strategy.

## Run the isolated benchmark

After applying migrations to a disposable PostgreSQL database:

```bash
python -m scripts.benchmark_duplicate_detection --pairs 5000
```

The benchmark creates a temporary table populated with deterministic synthetic English and Russian headline pairs. It compares Python scoring with PostgreSQL trigram candidate retrieval and reports:

- wall-clock query/runtime time;
- client process CPU time;
- candidate precision and recall against the labelled duplicate set;
- PostgreSQL `EXPLAIN ANALYZE` output, including buffers and chosen scan/index plan.

The temporary table is dropped at transaction end. No application articles or production data are read or modified.

## Interpretation and rollout gate

The benchmark's pg_trgm candidate recall is the key safety metric. A candidate prefilter must not be enabled merely because it is faster: any missed candidate can become a false negative. The current benchmark uses labelled synthetic examples, so production-like shadow evaluation on a protected staging copy is still required before rollout. The final Python threshold remains `DUPLICATE_TITLE_SIMILARITY_THRESHOLD`; trigram similarity is only a broad candidate filter and is not numerically interchangeable with `SequenceMatcher`.

Do not lower PostgreSQL's trigram similarity threshold globally. If future measurements require a custom threshold, scope it to the transaction and cover it with recall tests.
