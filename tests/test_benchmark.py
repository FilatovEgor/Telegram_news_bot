import asyncio
import csv
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.benchmark.dataset import BenchmarkArticle, load_dataset
from app.benchmark.pricing import ModelPricing
from app.benchmark.runner import BenchmarkRunner, write_results

def test_load_dataset_validates_and_rejects_duplicate_ids(tmp_path: Path):
    path = tmp_path / "dataset.jsonl"
    row = json.dumps({"article_id": "a1", "title": "Title", "content": "Body"})
    path.write_text(row + "\n", encoding="utf-8")
    assert load_dataset(path)[0].article_id == "a1"
    path.write_text(row + "\n" + row + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate article_id"):
        load_dataset(path)

def test_model_pricing_estimate():
    pricing = ModelPricing(0.1, 0.5)
    assert pricing.estimate(1_000_000, 1_000_000) == pytest.approx(0.6)
    with pytest.raises(ValueError, match="cannot be negative"):
        ModelPricing(-1, 0.5)

class FakeAgent:
    async def create_editorial_package(self, *args, **kwargs):
        package = SimpleNamespace(language="en", model_dump=lambda mode="json": {"language": "en", "summary": "test"})
        return SimpleNamespace(package=package, prompt_version="editorial-v1", input_tokens=100, output_tokens=50, attempt_count=1, duration_ms=20)

class FakeSession:
    def __init__(self):
        self.agent = FakeAgent()
        self.closed = False
    async def close(self):
        self.closed = True

def test_runner_records_usage_and_writes_review_template(tmp_path: Path):
    sessions = []
    def factory(model):
        session = FakeSession()
        sessions.append((model, session))
        return session
    article = BenchmarkArticle(article_id="a1", title="Title", content="Body")
    runner = BenchmarkRunner(factory, pricing={"model-a": ModelPricing(0.1, 0.5)})
    results = asyncio.run(runner.run([article], ["model-a"]))
    assert results[0].editorial_status == "success"
    assert results[0].input_tokens == 100
    assert results[0].estimated_cost_usd == pytest.approx(0.000035)
    assert sessions[0][1].closed is True
    output = write_results(results, tmp_path)
    assert (output / "results.jsonl").is_file()
    with (output / "human_review.csv").open(encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["article_id"] == "a1"
    assert row["factual_accuracy_1_5"] == ""
