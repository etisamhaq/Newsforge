from datetime import datetime, timezone

from app.config import get_settings
from app.extraction.base import ExtractionContext, ExtractionStrategy, StrategyResult
from app.extraction.llm import LLMArticle, LLMStrategy
from app.extraction.pipeline import ExtractionPipeline, default_registry
from tests.conftest import fixture_text

URL = "https://news.example.com/2024/05/14/city-approves-transit-plan"


async def test_jsonld_article_extraction():
    report = await ExtractionPipeline().run(URL, fixture_text("article_jsonld.html"))
    a = report.article
    assert a.is_article and a.article_score >= 0.9
    assert a.title == "City approves sweeping transit plan"
    assert a.authors == ["Jane Reporter", "John Writer"]
    assert a.published_at == datetime(2024, 5, 14, 8, 30, tzinfo=timezone.utc)
    assert a.modified_at == datetime(2024, 5, 14, 10, tzinfo=timezone.utc)
    assert a.category == "Local"
    assert a.tags == ["transit", "rail", "city council"]
    assert a.language == "en"
    assert a.canonical_url == URL  # tracking param stripped
    assert a.image_url == "https://news.example.com/images/rail.jpg"
    assert a.site_name == "Daily Example"
    assert a.description == "Three new light rail lines over the next decade."
    assert "light rail lines" in a.body and "Home" not in a.body
    assert a.word_count > 150
    assert a.confidence >= 0.85
    assert a.field_sources["title"] == "jsonld"
    assert not report.used_fallback


async def test_plain_html_extraction_without_structured_data():
    url = "https://gazette.example.org/news/storm-knocks-out-power-to-thousands"
    report = await ExtractionPipeline().run(url, fixture_text("article_plain.html"))
    a = report.article
    assert a.is_article
    assert a.title == "Storm knocks out power to thousands"
    assert a.authors == ["Sam Lee"]
    assert a.published_at == datetime(2024, 3, 2, 20, tzinfo=timezone.utc)
    assert "storm recovery plan" in a.body
    assert a.language == "en"  # detected from text
    assert 0.5 < a.confidence < 0.95


async def test_listing_page_is_not_article():
    report = await ExtractionPipeline().run("https://news.example.com/category/local", fixture_text("listing.html"))
    assert not report.article.is_article
    assert report.classification.score < 0.5


async def test_external_canonical_not_trusted():
    html = fixture_text("article_jsonld.html").replace(
        'href="https://news.example.com/2024/05/14/city-approves-transit-plan?utm_source=rss"',
        'href="https://victim.example.net/some-other-story"',
    ).replace('"mainEntityOfPage":"https://news.example.com/2024/05/14/city-approves-transit-plan",', "")
    a = (await ExtractionPipeline().run(URL, html)).article
    assert a.canonical_url == URL
    assert a.external_canonical == "https://victim.example.net/some-other-story"


async def test_noindex_detected():
    html = fixture_text("article_jsonld.html").replace("<head>", '<head><meta name="robots" content="noindex, nofollow">')
    a = (await ExtractionPipeline().run(URL, html)).article
    assert a.noindex and a.nofollow and not a.is_article


async def test_broken_strategy_does_not_break_pipeline():
    class Boom(ExtractionStrategy):
        name = "boom"
        priority = 1

        async def extract(self, ctx, merged):
            raise RuntimeError("kaput")

    reg = default_registry()
    reg.register(Boom())
    report = await ExtractionPipeline(reg).run(URL, fixture_text("article_jsonld.html"))
    assert report.article.is_article
    assert report.strategies[0].error.startswith("RuntimeError")


async def test_custom_strategy_can_be_registered():
    class Category(ExtractionStrategy):
        name = "custom-category"
        priority = 5

        async def extract(self, ctx: ExtractionContext, merged) -> StrategyResult:
            r = StrategyResult(self.name)
            r.add("category", "Custom", 0.99)
            return r

    reg = default_registry()
    reg.register(Category())
    a = (await ExtractionPipeline(reg).run(URL, fixture_text("article_jsonld.html"))).article
    assert a.category == "Custom"


class FakeLLM:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def extract_article(self, url, page_text, metadata):
        self.calls += 1
        return self.result


HARD_PAGE = (
    "<html><head><title>Loading…</title></head><body><div id='root'>"
    + "<div>Rescue crews worked through the night after the flood waters rose.<br></div>" * 30
    + "</div></body></html>"
)


def heuristics_plus_llm(llm):
    """Structured-data strategies + LLM only, so the fallback path is exercised deterministically."""
    reg = default_registry()
    reg.unregister("trafilatura")
    reg.unregister("density")
    from app.extraction.content import DensityStrategy

    class SignalsOnly(DensityStrategy):
        async def extract(self, ctx, merged):
            r = await super().extract(ctx, merged)
            r.fields.clear()
            return r

    reg.register(SignalsOnly())
    reg.register(LLMStrategy(llm, force_enabled=True), replace=True)
    return reg


async def test_llm_fallback_used_when_confidence_low():
    llm = FakeLLM(LLMArticle(
        is_article=True, title="Floodwaters recede", body="Rescue crews worked through the night. " * 60,
        authors=["A. Writer"], published_at="2024-06-01T12:00:00Z", language="en",
    ))
    report = await ExtractionPipeline(heuristics_plus_llm(llm)).run(
        "https://news.example.com/2024/06/01/floodwaters-recede-after-storm", HARD_PAGE
    )
    assert llm.calls == 1 and report.used_fallback
    a = report.article
    assert a.is_article and a.title == "Floodwaters recede"
    assert a.authors == ["A. Writer"]
    assert a.field_sources["body"] == "llm"


async def test_llm_not_called_for_high_confidence_pages():
    llm = FakeLLM(None)
    reg = default_registry()
    reg.register(LLMStrategy(llm, force_enabled=True), replace=True)
    report = await ExtractionPipeline(reg).run(URL, fixture_text("article_jsonld.html"))
    assert llm.calls == 0 and not report.used_fallback


async def test_llm_disabled_by_default():
    assert get_settings().llm_enabled is False
    assert all(s.name != "llm" for s in default_registry().fallbacks())


async def test_report_serializes():
    report = await ExtractionPipeline().run(URL, fixture_text("article_jsonld.html"))
    d = report.to_dict()
    assert d["article"]["published_at"].startswith("2024-05-14")
    assert {s["strategy"] for s in d["strategies"]} >= {"jsonld", "metatags", "trafilatura", "density"}


async def test_llm_rejection_marks_non_article():
    llm = FakeLLM(LLMArticle(is_article=False))
    report = await ExtractionPipeline(heuristics_plus_llm(llm)).run(
        "https://news.example.com/2024/06/01/floodwaters-recede-after-storm", HARD_PAGE
    )
    assert llm.calls == 1 and not report.article.is_article


async def test_llm_errors_are_contained():
    class Broken:
        async def extract_article(self, *a):
            raise TimeoutError("slow")

    report = await ExtractionPipeline(heuristics_plus_llm(Broken())).run(
        "https://news.example.com/2024/06/01/floodwaters-recede-after-storm", HARD_PAGE
    )
    assert report.used_fallback
    assert any(s.strategy == "llm" and s.error for s in report.strategies)


async def test_groq_client_parses_structured_output():
    import json

    import httpx

    from app.extraction.llm import GroqLLMClient

    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        if "retried" not in seen:
            seen["retried"] = True
            return httpx.Response(429, headers={"retry-after": "0"})
        content = json.dumps({"is_article": True, "title": "Floods", "body": "Water rose. " * 50,
                              "authors": ["A. B."], "published_at": "2024-06-01T00:00:00Z", "tags": [], "language": "en"})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]})

    client = GroqLLMClient(api_key="test-key", transport=httpx.MockTransport(handler))
    out = await client.extract_article("https://x.com/a", "page text", "meta")
    await client.aclose()
    assert out.title == "Floods" and out.authors == ["A. B."]
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["response_format"]["type"] == "json_schema"
    assert seen["body"]["model"] == "openai/gpt-oss-120b"


async def test_groq_client_rejects_invalid_or_truncated_output():
    import httpx

    from app.extraction.llm import GroqLLMClient

    replies = iter([
        {"choices": [{"finish_reason": "length", "message": {"content": "{"}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]},
    ])
    client = GroqLLMClient(api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=next(replies))))
    assert await client.extract_article("u", "t", "m") is None
    assert await client.extract_article("u", "t", "m") is None
    await client.aclose()


async def test_provider_selection(monkeypatch):
    from app.extraction.llm import GroqLLMClient, make_llm_client

    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "groq")
    assert make_llm_client() is None  # no key
    monkeypatch.setattr(s, "groq_api_key", "k")
    assert isinstance(make_llm_client(), GroqLLMClient)
