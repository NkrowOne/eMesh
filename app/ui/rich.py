"""✨ Rich panels: a panel's plain text (Telegram HTML with line breaks) as a rich message (Bot API 10.1).

The screens keep writing their text as always (``docs/ARCHITECTURE.md``, text conventions) and :func:`to_rich` turns
it into rich HTML when ``show()`` sends it:

* the title (``📣 <b>Canales y grupos</b>``) and the lines under it become a card: a bordered one-column table with
  the title as its header;
* a numbered list (``1. …`` with its ``   └ details``) becomes ``<ol>``;
* a block in italics (a legend, a hint) becomes the ``<footer>``;
* anything else is a paragraph.

Rich HTML is not Telegram HTML: a line break is ``<br>`` or a new block, never ``\\n``. When a text can't be converted
safely (``<pre>``, a tag left open across blocks) :func:`to_rich` returns None and the plain text is sent.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

NBSP = " "
_TITLE_RE = re.compile(r"^[^<\n]{0,12}<b>(?P<title>[^<\n]{1,64})</b>[^\n]{0,48}$")
_ITEM_RE = re.compile(r"^(\d+)\. (.*)$")
_INDENT_RE = re.compile(r"^ +")
_PRE_RE = re.compile(r"<pre>.*?</pre>", re.S)
_PRE_BLOCK_RE = re.compile(r"^(?P<before>.*?)(?P<pre><pre>.*</pre>)(?P<after>.*)$", re.S)
_LINE_BREAK = "\x00"  # a line break inside <pre> while the text is cut in blocks and lines
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)[^>]*?(/?)>")
_VOID = {"br", "hr", "img"}
# What the plain panels use and rich HTML takes as it is.
_INLINE = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "a", "tg-spoiler", "tg-emoji",
           "tg-time", "blockquote"}
_ALLOWED = _INLINE | _VOID | {"table", "tr", "th", "td", "ol", "ul", "li", "p", "footer", "cite", "pre"}


def _balanced(fragment: str) -> bool:
    """Every tag opened in ``fragment`` is closed in it, in order, and all of them are known."""
    stack: list[str] = []
    for closing, name, self_closing in _TAG_RE.findall(fragment):
        name = name.lower()
        if name not in _ALLOWED:
            return False
        if name in _VOID or self_closing:
            continue
        if not closing:
            stack.append(name)
        elif not stack or stack.pop() != name:
            return False
    return not stack


def _lines(block: str) -> str:
    """The lines of a block joined with ``<br>``; the indent of a ``   └ hint`` line is kept with no-break spaces."""
    out = []
    for line in block.split("\n"):
        indent = _INDENT_RE.match(line)
        out.append(NBSP * len(indent.group()) + line[len(indent.group()):] if indent else line)
    return "<br>".join(out)


def _is_title(line: str) -> bool:
    match = _TITLE_RE.match(line)
    return bool(match) and not match.group("title").rstrip().endswith((".", ":", "?", "!"))


def _as_list(block: str) -> str | None:
    """``1. item`` lines (each with its indented detail lines) as ``<ol>``, or None when the block isn't such a list."""
    items: list[list[str]] = []
    start = None
    for line in block.split("\n"):
        match = _ITEM_RE.match(line)
        if match:
            number = int(match.group(1))
            if start is None:
                start = number
            elif number != start + len(items):
                return None
            items.append([match.group(2)])
        elif items and line.startswith(" "):
            items[-1].append(line.strip())
        else:
            return None
    if not items or start is None:
        return None
    body = "".join(f"<li>{'<br>'.join(item)}</li>" for item in items)
    return f"<ol>{body}</ol>" if start == 1 else f'<ol start="{start}">{body}</ol>'


def _as_bullets(block: str) -> str | None:
    """``• item`` lines as ``<ul>``, or None when some line of the block is something else."""
    lines = block.split("\n")
    if len(lines) < 2 or not all(line.startswith("• ") for line in lines):
        return None
    return "<ul>" + "".join(f"<li>{line[2:]}</li>" for line in lines) + "</ul>"


def _with_pre(block: str) -> str | None:
    """A block with a ``<pre>`` example: the lines around it are paragraphs and the example keeps its line breaks."""
    match = _PRE_BLOCK_RE.match(block)
    if match is None:
        return None
    before, after = match.group("before").strip("\n"), match.group("after").strip("\n")
    return ((f"<p>{_lines(before)}</p>" if before else "") + match.group("pre")
            + (f"<p>{_lines(after)}</p>" if after else ""))


def _is_footer(block: str) -> bool:
    return block.startswith("<i>") and block.endswith("</i>") and block.count("<i>") == 1


def to_rich(text: str) -> str | None:
    """``text`` (a plain panel) as rich HTML, or None when it must stay plain."""
    if not text.strip() or "\r" in text or _LINE_BREAK in text:
        return None
    text = _PRE_RE.sub(lambda m: m.group().replace("\n", _LINE_BREAK), text)  # an example is never cut in blocks
    blocks = [b.strip("\n") for b in re.split(r"\n{2,}", text.strip("\n")) if b.strip()]
    if not all(_balanced(b) for b in blocks):
        return None
    out: list[str] = []
    title_at = next((i for i, b in enumerate(blocks[:3]) if _is_title(b.split("\n", 1)[0])), None)
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if i == title_at:
            head, _, body = block.partition("\n")
            # A title alone takes the next block into its card (unless that one is a list or a legend).
            if not body and i + 1 < len(blocks) and _as_list(blocks[i + 1]) is None and not _is_footer(blocks[i + 1]):
                body = blocks[i + 1]
                i += 1
            cell = f"<tr><td>{_lines(body)}</td></tr>" if body else ""
            out.append(f"<table bordered><tr><th>{head}</th></tr>{cell}</table>")
        elif (listed := _as_list(block) or _as_bullets(block)) is not None:
            out.append(listed)
        elif "<pre>" in block:
            pre = _with_pre(block)
            if pre is None:
                return None
            out.append(pre)
        elif _is_footer(block):
            out.append(f"<footer>{_lines(block[3:-4])}</footer>")
        elif block.startswith("<blockquote") and block.endswith("</blockquote>"):
            out.append(_lines(block))
        else:
            out.append(f"<p>{_lines(block)}</p>")
        i += 1
    html = "".join(out)
    if not well_formed(html):
        return None
    return html.replace(_LINE_BREAK, "\n")


class _Checker(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.ok = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _ALLOWED:
            self.ok = False
        elif tag not in _VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if not self.stack or self.stack.pop() != tag:
            self.ok = False


def well_formed(html: str) -> bool:
    """Known tags only, properly nested, and no raw line break outside them (rich HTML ignores it)."""
    if "\n" in html:  # (the line breaks of a <pre> are still marked when this runs)
        return False
    checker = _Checker()
    checker.feed(html)
    checker.close()
    return checker.ok and not checker.stack
