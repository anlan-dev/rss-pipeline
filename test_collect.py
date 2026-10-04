# -*- coding: utf-8 -*-
"""collect.py 的回归测试。

覆盖：RSS/Atom 解析、条目标准化、去重、规则过滤、日报生成。
运行：python -m unittest test_collect -v
"""
import unittest
from datetime import datetime, timezone

import collect


RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Test Feed</title>
  <item>
    <title>First post</title>
    <link>https://example.com/1</link>
    <guid>guid-1</guid>
    <pubDate>Mon, 01 Sep 2026 10:00:00 GMT</pubDate>
    <description>hello &amp; world</description>
  </item>
  <item>
    <title>Second post</title>
    <link>https://example.com/2</link>
    <guid>guid-2</guid>
    <pubDate>Tue, 02 Sep 2026 10:00:00 GMT</pubDate>
    <description>noise</description>
  </item>
</channel></rss>
"""

ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Atom</title>
  <entry>
    <title>Atom entry</title>
    <link href="https://example.com/a"/>
    <id>urn:uuid:a</id>
    <updated>2026-09-03T10:00:00Z</updated>
    <summary>atom summary</summary>
  </entry>
</feed>
"""


class TestParse(unittest.TestCase):
    def test_parse_rss_returns_two_items(self):
        items = collect.parse_feed(RSS_XML)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "First post")

    def test_parse_atom_returns_one_item(self):
        items = collect.parse_feed(ATOM_XML)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Atom entry")
        self.assertEqual(items[0]["link"], "https://example.com/a")

    def test_parse_rss_unescapes_html(self):
        items = collect.parse_feed(RSS_XML)
        self.assertEqual(items[0]["summary"], "hello & world")


class TestNormalize(unittest.TestCase):
    def _feed(self):
        return {"id": "t", "name": "Test", "category": "科技", "tier": "A"}

    def test_normalize_fills_fields(self):
        raw = {"title": "T", "link": "https://x/1", "guid": "g1",
               "published": "2026-09-01T10:00:00+00:00", "summary": "s"}
        e = collect.normalize_entry(raw, self._feed())
        self.assertEqual(e["source_id"], "t")
        self.assertEqual(e["source_name"], "Test")
        self.assertEqual(e["category"], "科技")
        self.assertIn("id", e)

    def test_normalize_uses_guid_as_id(self):
        raw = {"title": "T", "link": "https://x/1", "guid": "g1",
               "published": "2026-09-01T10:00:00+00:00", "summary": "s"}
        e = collect.normalize_entry(raw, self._feed())
        self.assertEqual(e["id"], "g1")

    def test_normalize_falls_back_to_link(self):
        raw = {"title": "T", "link": "https://x/1", "guid": "",
               "published": "2026-09-01T10:00:00+00:00", "summary": "s"}
        e = collect.normalize_entry(raw, self._feed())
        self.assertEqual(e["id"], "https://x/1")


class TestDedupe(unittest.TestCase):
    def test_dedupe_removes_same_id(self):
        e1 = {"id": "a", "title": "one"}
        e2 = {"id": "a", "title": "two"}
        e3 = {"id": "b", "title": "three"}
        kept, seen = collect.dedupe([e1, e2, e3], set())
        self.assertEqual([x["id"] for x in kept], ["a", "b"])

    def test_dedupe_respects_existing_seen(self):
        seen = {"a"}
        kept, new_seen = collect.dedupe([{"id": "a"}, {"id": "b"}], seen)
        self.assertEqual([x["id"] for x in kept], ["b"])
        self.assertIn("b", new_seen)


class TestFilter(unittest.TestCase):
    def _feed(self, blacklist=None, whitelist=None):
        return {"filters": {"title_blacklist": blacklist or [],
                            "title_whitelist": whitelist or []}}

    def test_blacklist_drops_match(self):
        e = {"id": "1", "title": "卢昌海 微博选录"}
        kept, dropped = collect.apply_filter([e], self._feed(blacklist=["微博"]))
        self.assertEqual(kept, [])
        self.assertEqual(len(dropped), 1)

    def test_whitelist_keeps_only_match(self):
        e1 = {"id": "1", "title": "AI 进展"}
        e2 = {"id": "2", "title": "周末随笔"}
        kept, dropped = collect.apply_filter(
            [e1, e2], self._feed(whitelist=["AI"]))
        self.assertEqual([x["id"] for x in kept], ["1"])

    def test_no_filter_keeps_all(self):
        kept, dropped = collect.apply_filter([{"id": "1", "title": "x"}], self._feed())
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])


class TestEncodeUrl(unittest.TestCase):
    def test_encodes_chinese(self):
        self.assertEqual(
            collect._encode_url("http://localhost:1200/x?filter=赞同"),
            "http://localhost:1200/x?filter=%E8%B5%9E%E5%90%8C")

    def test_keeps_already_encoded(self):
        self.assertEqual(
            collect._encode_url("http://a.com/p%20ath?a=1"),
            "http://a.com/p%20ath?a=1")


class TestDateFallback(unittest.TestCase):
    def test_extracts_date_from_slash_url(self):
        self.assertEqual(
            collect._date_from_link("https://tech.meituan.com/2026/07/28/x.html"),
            "2026-07-28T00:00:00+00:00")

    def test_extracts_date_from_dash_url(self):
        self.assertEqual(
            collect._date_from_link("https://a.com/2026-07-28/post"),
            "2026-07-28T00:00:00+00:00")

    def test_returns_empty_when_no_date(self):
        self.assertEqual(collect._date_from_link("https://a.com/about"), "")

    def test_normalize_uses_link_date_when_published_missing(self):
        raw = {"title": "T", "link": "https://tech.meituan.com/2026/07/28/x.html",
               "guid": "g1", "published": "", "summary": "s"}
        feed = {"id": "t", "name": "Test", "category": "科技", "tier": "A"}
        e = collect.normalize_entry(raw, feed)
        self.assertEqual(e["published"], "2026-07-28T00:00:00+00:00")


class TestFetchRetry(unittest.TestCase):
    def setUp(self):
        self._orig = collect.time.sleep
        collect.time.sleep = lambda *_: None

    def tearDown(self):
        collect.time.sleep = self._orig

    def test_retries_on_incomplete_read_then_succeeds(self):
        import http.client
        from unittest import mock

        calls = {"n": 0}

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"ok"

        def fake_urlopen(req, timeout=0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise http.client.IncompleteRead(b"partial")
            return FakeResp()

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            out = collect.fetch("http://x", retries=1)
        self.assertEqual(out, b"ok")
        self.assertEqual(calls["n"], 2)


class TestDigest(unittest.TestCase):
    def test_build_digest_has_header_and_rows(self):
        entries = [{
            "id": "1", "title": "Post", "link": "https://x/1",
            "published": "2026-09-01T10:00:00+00:00",
            "source_name": "Test", "category": "科技", "tier": "A",
            "summary": "s",
        }]
        md = collect.build_digest(entries, {"total": 1, "kept": 1, "dropped": 0})
        self.assertIn("# RSS 信息日报", md)
        self.assertIn("Post", md)
        self.assertIn("https://x/1", md)

    def test_build_digest_has_frontmatter(self):
        md = collect.build_digest([], {"total": 0, "kept": 0, "dropped": 0})
        self.assertTrue(md.startswith("---\n"))
        self.assertIn("tags:", md)
        self.assertIn("rss", md)


if __name__ == "__main__":
    unittest.main()
