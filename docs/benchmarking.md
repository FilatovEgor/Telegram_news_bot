# AI model benchmark

The benchmark is an offline evaluation tool for the editorial AI pipeline. It calls the existing EditorialAgent directly and never connects to Telegram, the database, ingestion, moderation, or publishing services. It does not approve or publish generated material.

## Dataset

Create a UTF-8 JSONL file with one article per line, using stable non-sensitive IDs and identical source text for each model:

~~~json
{"article_id":"sample-001","title":"Article headline","content":"Full article text...","source_url":"https://example.org/article","tags":["technology"]}
~~~

This is a schema example, not benchmark evidence. Aim for 100–200 representative articles: short and long stories, technical topics, ambiguous stories, and both Russian and English sources. Remove personal data and credentials.

## Run

Set OPENAI_API_KEY in the local environment or .env and ensure AI_PROVIDER=openai. The CLI supplies a placeholder DATABASE_URL because application settings require it, but it never opens a database connection.

~~~bash
python -m app.benchmark.cli --dataset data/benchmark/articles.jsonl --models gpt-6-luna,gpt-5.6-sol --limit 5
~~~

Omit --limit for the full dataset. Use model IDs enabled for the API account. Runs are sequential. Russian editorial outputs also run through the existing RU-to-EN translation method; other languages skip translation. Failed articles are recorded without stopping the run.

## Optional pricing

Prices are not hard-coded. Supply a JSON file with current per-model rates and pass it with --pricing-json pricing.json:

~~~json
{
  "gpt-6-luna": {"input_usd_per_million": 0.10, "output_usd_per_million": 0.50},
  "gpt-5.6-sol": {"input_usd_per_million": 0.40, "output_usd_per_million": 2.00}
}
~~~

These values are illustrative only; replace them with current account-applicable prices. Without a pricing file, estimated cost is blank rather than guessed.

## Artifacts and review

Each run creates a timestamped directory under data/benchmark/runs/ with results.jsonl, metrics.csv, and human_review.csv. The human review file contains blank scores for factual accuracy, completeness, hallucination severity, editorial quality, translation fidelity, critical hallucination, acceptance, and reviewer notes.

Score outputs blind to model identity where practical. Use 1–5 for quality dimensions. Mark critical factual hallucinations explicitly and treat them as failures regardless of style. Compare models on identical article IDs; do not treat model-reported confidence as factual accuracy.

## Safety and limitations

The harness measures editorial-package generation and RU-to-EN translation, not a standalone classifier or independent fact-checker. Existing prompts, validation, and allowlisted tools are reused. Results remain suggestions; human approval is mandatory in production. API calls incur charges. Start with --limit 5 before a larger run.
