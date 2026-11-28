# Phase 4C — duplicate detection benchmark

The production matcher remains unchanged and conservative:

1. canonical URL and content-hash matches remain exact fast paths;
2. Python `SequenceMatcher` with the existing normalized-title implementation remains the final title decision;
3. duplicate pairs remain `PENDING` for human review.

No permanent GIN index or schema migration is added in this phase. The benchmark installs `pg_trgm` only in the disposable benchmark database and builds its index on a temporary table. This avoids changing the application schema before performance and recall are demonstrated.

## Run the isolated benchmark

Use a disposable PostgreSQL database (the CI service is suitable):

```bash
python -m scripts.benchmark_duplicate_detection --pairs 5000
```

The benchmark creates a temporary table populated with deterministic synthetic English and Russian headline pairs. It compares Python scoring with PostgreSQL trigram candidate retrieval and reports:

- wall-clock runtime and client process CPU time;
- Python matcher precision and recall against generated labels;
- pg_trgm candidate recall and candidate-set reduction;
- PostgreSQL `EXPLAIN ANALYZE` output, including buffers and chosen scan/index plan.

The temporary table is dropped at transaction end. No application articles or production data are read or modified. The extension is created in the disposable benchmark database, not in application migrations.

## Interpretation and rollout gate

The pg_trgm candidate recall is the key safety metric. A candidate prefilter must not be enabled merely because it is faster: any missed candidate can become a false negative. Synthetic labels are useful for repeatable regression tests, but they are not human-reviewed production truth. Production-like shadow evaluation on a protected staging copy is required before rollout.

The final Python threshold remains `DUPLICATE_TITLE_SIMILARITY_THRESHOLD`; trigram similarity is only a broad candidate filter and is not numerically interchangeable with `SequenceMatcher`. The current phase does not switch the production algorithm or alter candidate review behavior.

Do not lower PostgreSQL's trigram similarity threshold globally. If future measurements require a custom threshold, scope it to the transaction and cover it with recall tests.
