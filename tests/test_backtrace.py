"""Tests for backtrace parsing."""
from __future__ import annotations

from bs4 import BeautifulSoup

from symfony_profiler_client.backtrace import parse_hidden_block


MODERN_BLOCK = """
<div class="hidden">
<table>
  <thead><tr><th>#</th><th>File/Call</th></tr></thead>
  <tbody>
    <tr>
      <td>1</td>
      <td>
        <a href="file:///app/src/Service/Foo.php#L10">App\\Service\\Foo->bar</a>
        (line 10)
      </td>
    </tr>
    <tr>
      <td>2</td>
      <td>
        <a href="file:///app/vendor/foo/lib.php#L20">Foo\\Lib->baz</a>
        (line 20)
      </td>
    </tr>
  </tbody>
</table>
</div>
"""


LEGACY_BLOCK = """
<div class="hidden">
<ol>
  <li>
    <a>1</a>
    <pre>App\\Service\\Foo->bar
(line 10)</pre>
  </li>
</ol>
</div>
"""


def test_modern_table_parses_two_frames():
    soup = BeautifulSoup(MODERN_BLOCK, "lxml")
    hidden = soup.find("div", class_="hidden")
    frames = parse_hidden_block(hidden)
    assert len(frames) == 2
    assert frames[0]["class"] == "App\\Service\\Foo"
    assert frames[0]["method"] == "bar"
    assert frames[0]["line"] == 10
    assert frames[0]["is_src"] is True
    assert frames[1]["is_vendor"] is True


def test_legacy_ol_parses_one_frame():
    soup = BeautifulSoup(LEGACY_BLOCK, "lxml")
    hidden = soup.find("div", class_="hidden")
    frames = parse_hidden_block(hidden)
    assert len(frames) == 1
    assert frames[0]["class"] == "App\\Service\\Foo"
    assert frames[0]["method"] == "bar"
    assert frames[0]["line"] == 10


def test_empty_block_returns_empty_list():
    soup = BeautifulSoup('<div class="hidden"></div>', "lxml")
    hidden = soup.find("div", class_="hidden")
    assert parse_hidden_block(hidden) == []
