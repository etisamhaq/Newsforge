from app.crawler.urls import normalize_url
from app.dedup.hashing import bands, content_hash, hamming, simhash, to_signed, to_unsigned
from app.extraction.pipeline import ExtractedArticle
from app.services.articles import ArticleRepository

TEXT = " ".join(
    f"Sentence number {i} describes the council vote on the transit plan and its funding sources." for i in range(40)
)


def test_content_hash_normalizes():
    assert content_hash("Hello,   World!") == content_hash("hello world")
    assert content_hash("") is None


def test_simhash_similarity():
    a = simhash(TEXT)
    b = simhash(TEXT.replace("number 7 ", "number seven "))
    c = simhash("Completely different text about football results and the weather this weekend. " * 20)
    assert hamming(a, b) <= 6
    assert hamming(a, c) > 10
    assert to_unsigned(to_signed(a)) == a
    assert len(bands(a)) == 4


def _article(url, body=TEXT, title="Transit plan", conf=0.9):
    u = normalize_url(url)
    return ExtractedArticle(url=u, canonical_url=u, title=title, body=body, word_count=len(body.split()),
                            confidence=conf, article_score=0.9, is_article=True, primary_method="jsonld")


async def test_repository_dedup_layers(session, workspace):
    repo = ArticleRepository(session, workspace_id=workspace.id)
    r1 = await repo.upsert(_article("https://a.com/story-one"), None)
    assert r1.outcome == "new"
    r2 = await repo.upsert(_article("https://a.com/story-one"), None)
    assert r2.outcome == "unchanged" and r2.article.id == r1.article.id
    r3 = await repo.upsert(_article("https://a.com/story-one", body=TEXT + " Update: more."), None)
    assert r3.outcome == "updated" and r3.article.id == r1.article.id
    r4 = await repo.upsert(_article("https://b.com/syndicated", body=TEXT + " Update: more."), None)
    assert r4.outcome == "duplicate" and r4.duplicate_of == r1.article.id
    near = TEXT.replace("Sentence number 3 ", "Sentence no. 3 ") + " Update: more."
    r5 = await repo.upsert(_article("https://c.com/rewritten", body=near), None)
    assert r5.outcome == "near_duplicate" and r5.duplicate_of == r1.article.id
    r6 = await repo.upsert(_article("https://d.com/other", body="Totally unrelated story about a cat show. " * 30), None)
    assert r6.outcome == "new"


async def test_worse_extraction_does_not_overwrite(session, workspace):
    repo = ArticleRepository(session, workspace_id=workspace.id)
    await repo.upsert(_article("https://a.com/x", conf=0.95), None)
    r = await repo.upsert(_article("https://a.com/x", body="short teaser text", conf=0.3), None)
    assert r.outcome == "unchanged" and r.article.body == TEXT


async def test_raw_html_stored_compressed(session, workspace):
    import gzip

    from sqlalchemy import select

    from app.db.models import RawDocument

    repo = ArticleRepository(session, workspace_id=workspace.id)
    await repo.upsert(_article("https://a.com/raw"), None, raw_html=b"<html>raw</html>", raw_meta={"status_code": 200})
    raw = (await session.execute(select(RawDocument))).scalar_one()
    assert gzip.decompress(raw.content_gzip) == b"<html>raw</html>"
