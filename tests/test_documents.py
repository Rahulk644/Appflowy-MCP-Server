"""Local document conversion, formatting and loss-prevention regressions."""

from appflowy_mcp import documents


def test_dollar_amounts_survive_markdown_parsing():
    # Regression: with dollarmath's defaults, a sentence with two dollar AMOUNTS had
    # everything between them swallowed into a math node —
    #   "ARR hit $560k this quarter, up from $380k last year."
    #     -> "ARR hit 380k last year."
    # Silent, unrecoverable loss of figures in ordinary prose.
    money = "ARR hit $560k this quarter, up from $380k last year."
    blocks = documents._md_to_blocks(money)
    rendered = " ".join(
        seg.get("insert", "")
        for b in blocks
        for seg in (b.get("data", {}) or {}).get("delta", [])
    )
    assert "$560k" in rendered
    assert "$380k" in rendered
    assert "this quarter, up from" in rendered  # the text between them survives


def test_inline_math_still_parses():
    # The money fix must not cost us real math: a TeX expression with no digit or
    # space against the delimiter is still math, and $$...$$ blocks are untouched.
    toks = documents._md_parser.parse("Euler: $e^{i\\pi}+1=0$ done")
    kinds = {c.type for t in toks if t.type == "inline" for c in (t.children or [])}
    assert "math_inline" in kinds

    blocks = documents._md_to_blocks("$$\nx^2 + y^2 = z^2\n$$")
    assert any(b.get("type") == "math_equation" for b in blocks)


def test_add_blocks_batch_insert():
    # add_blocks folds a whole Markdown checklist into a card in one pass; verify the
    # block-tree inserter lands every block by rendering the doc back to Markdown.
    from pycrdt import Array, Doc, Map

    doc = Doc()
    root = doc.get("data", type=Map)
    with doc.transaction():
        root["document"] = Map(
            {
                "blocks": Map(
                    {"page": Map({"ty": "page", "data": "{}", "children": "pc"})}
                ),
                "meta": Map(
                    {"children_map": Map({"pc": Array([])}), "text_map": Map()}
                ),
                "page_id": "page",
            }
        )
        d = root["document"]
        bmap, cmap, tmap = d["blocks"], d["meta"]["children_map"], d["meta"]["text_map"]
        specs = documents._md_to_blocks(
            "## Plan\n- [ ] first item\n- [ ] **bold** second\n\nplain note"
        )
        for spec in specs:
            cmap["pc"].append(
                documents._insert_pd_block(bmap, cmap, tmap, spec, "page")
            )
    md = documents._doc_to_markdown(d)
    assert "## Plan" in md
    assert "- [ ] first item" in md
    assert "- [ ] **bold** second" in md
    assert "plain note" in md
    assert len(list(cmap["pc"])) == 4  # heading + 2 todos + paragraph, one fold


def test_set_text_utf8_offsets_with_emoji():
    # pycrdt Text indexes by UTF-8 byte; a leading emoji (4 bytes) must not drift the
    # format range, or links/bold after it land on the wrong characters.
    from pycrdt import Doc, Text

    d = Doc()
    t = d.get("t", type=Text)
    with d.transaction():
        documents._set_text(
            t,
            [
                {"insert": "🔗 see "},
                {"insert": "PREP-380", "attributes": {"href": "http://x"}},
                {"insert": " now"},
            ],
        )
    assert t.diff() == [
        ("🔗 see ", None),
        ("PREP-380", {"href": "http://x"}),
        (" now", None),
    ]


def test_md_to_blocks_covers_core_palette():
    # The Markdown content interface: one string -> the AppFlowy block tree
    # create_page / append_blocks feed to AppFlowy.
    md = (
        "# Title\n\n"
        "Some **bold**, *italic*, `code`, ~~struck~~, and [a link](http://x.com).\n\n"
        "- one\n"
        "- two\n"
        "  - nested\n"
        "- [ ] todo\n"
        "- [x] done\n\n"
        "1. first\n"
        "2. second\n\n"
        "> quoted line\n\n"
        '```python\nprint("hi")\n```\n\n'
        "---\n\n"
        "![pic](http://img/p.png)\n"
    )
    blocks = documents._md_to_blocks(md)

    assert blocks[0] == {
        "type": "heading",
        "data": {"level": 1, "delta": [{"insert": "Title"}]},
    }
    # inline formatting in the paragraph
    ops = next(b for b in blocks if b["type"] == "paragraph")["data"]["delta"]
    assert {"insert": "bold", "attributes": {"bold": True}} in ops
    assert {"insert": "italic", "attributes": {"italic": True}} in ops
    assert {"insert": "code", "attributes": {"code": True}} in ops
    assert {"insert": "struck", "attributes": {"strikethrough": True}} in ops
    assert any(o.get("attributes", {}).get("href") == "http://x.com" for o in ops)
    # lists: nesting + GFM task state (checked/unchecked, marker stripped)
    assert any(b["type"] == "bulleted_list" and "children" in b for b in blocks)
    todos = [b for b in blocks if b["type"] == "todo_list"]
    assert [t["data"]["checked"] for t in todos] == [False, True]
    assert [t["data"]["delta"][0]["insert"] for t in todos] == ["todo", "done"]
    assert any(b["type"] == "numbered_list" for b in blocks)
    # quote, code (with language), divider, image block
    assert any(b["type"] == "quote" for b in blocks)
    code = next(b for b in blocks if b["type"] == "code")
    assert code["data"]["language"] == "python"
    assert code["data"]["delta"][0]["insert"] == 'print("hi")'
    assert any(b["type"] == "divider" for b in blocks)
    img = next(b for b in blocks if b["type"] == "image")
    assert img["data"]["url"] == "http://img/p.png"
    assert img["data"]["image_type"] == 2


def test_md_to_blocks_empty_and_fallback():
    assert documents._md_to_blocks("") == []
    assert documents._md_to_blocks("   \n") == []
    # Unsupported HTML degrades to plaintext, never dropped.
    blocks = documents._md_to_blocks("<aside>Preserve this content</aside>")
    assert blocks and all(b["type"] == "paragraph" for b in blocks)
    assert (
        "".join(o["insert"] for b in blocks for o in b["data"]["delta"]).strip() != ""
    )


def test_inline_md_formatting():
    f = documents._inline_md
    assert f([("plain", None)]) == "plain"
    assert f([("b", {"bold": True})]) == "**b**"
    assert f([("i", {"italic": True})]) == "*i*"
    assert f([("s", {"strikethrough": True})]) == "~~s~~"
    assert f([("c", {"code": True})]) == "`c`"
    assert f([("x", {"href": "http://u"})]) == "[x](http://u)"
    assert f([("x", {"bold": True, "italic": True})]) == "***x***"
    assert f([("x", {"bold": True, "href": "http://u"})]) == "[**x**](http://u)"


def test_doc_to_markdown_renders_blocks():
    # Mirrors AppFlowy's real document collab: block.data holds type fields, text
    # lives in text_map as a yjs Text whose diff() yields the delta.
    from pycrdt import Array, Doc, Map, Text

    doc = Doc()
    root = doc.get("data", type=Map)
    with doc.transaction():
        root["document"] = Map(
            {
                "blocks": Map(),
                "meta": Map({"children_map": Map(), "text_map": Map()}),
                "page_id": "page",
            }
        )
        document = root["document"]
        blocks = document["blocks"]
        cmap = document["meta"]["children_map"]
        tmap = document["meta"]["text_map"]

        def add(bid, ty, data, ckey, text=None):
            m = {"ty": ty, "data": data, "children": ckey}
            if text is not None:
                ext = "x" + bid
                m["external_id"] = ext
                tmap[ext] = Text(text)
            blocks[bid] = Map(m)

        add("page", "page", "{}", "pc")
        cmap["pc"] = Array(["h", "b1", "b2", "t1", "c1"])
        add("h", "heading", '{"level":2}', "hc", "Title")
        cmap["hc"] = Array([])
        add("b1", "bulleted_list", "{}", "b1c", "parent")
        cmap["b1c"] = Array(["b1n"])
        add("b1n", "bulleted_list", "{}", "b1nc", "child")
        cmap["b1nc"] = Array([])
        add("b2", "bulleted_list", "{}", "b2c", "sibling")
        cmap["b2c"] = Array([])
        add("t1", "todo_list", '{"checked":true}', "t1c", "done")
        cmap["t1c"] = Array([])
        add("c1", "code", '{"language":"py"}', "c1c", "x=1\ny=2")
        cmap["c1c"] = Array([])
    md = documents._doc_to_markdown(root["document"])
    assert "## Title" in md
    assert "- parent\n  - child" in md  # nested item indented under its parent
    assert "- sibling" in md
    assert "- [x] done" in md
    assert "```py\nx=1\ny=2\n```" in md


def test_md_inline_and_set_text():
    from pycrdt import Doc, Map, Text

    delta = documents._md_inline_to_delta("a **b** ~~c~~ [x](http://u) `k`")
    assert {"insert": "b", "attributes": {"bold": True}} in delta
    assert {"insert": "c", "attributes": {"strikethrough": True}} in delta
    assert {"insert": "k", "attributes": {"code": True}} in delta
    assert any(o.get("attributes", {}).get("href") == "http://u" for o in delta)

    doc = Doc()
    m = doc.get("t", type=Map)
    with doc.transaction():
        m["x"] = Text("stale")
        documents._set_text(m["x"], delta)  # overwrites, applies formatting ranges
    diff = m["x"].diff()
    assert "".join(seg for seg, _ in diff) == "a b c x k"
    assert ("b", {"bold": True}) in diff
    assert ("k", {"code": True}) in diff


def test_callout_and_math_blocks():
    blocks = documents._md_to_blocks(
        "> [!WARNING]\n> Be careful here.\n\n$$\nE=mc^2\n$$"
    )
    callout = next(b for b in blocks if b["type"] == "callout")
    assert callout["data"]["icon"] == "⚠️"
    assert callout["data"]["delta"] == [{"insert": "Be careful here."}]
    math = next(b for b in blocks if b["type"] == "math_equation")
    assert math["data"]["formula"] == "E=mc^2"
    # inline math survives as literal $...$
    para = documents._md_to_blocks("mass $m$ energy")[0]
    assert "$m$" in "".join(o["insert"] for o in para["data"]["delta"])


def test_doc_to_markdown_callout_math_toggle():
    from pycrdt import Array, Doc, Map, Text

    doc = Doc()
    root = doc.get("data", type=Map)
    with doc.transaction():
        root["document"] = Map(
            {
                "blocks": Map(),
                "meta": Map({"children_map": Map(), "text_map": Map()}),
                "page_id": "page",
            }
        )
        d = root["document"]
        blocks = d["blocks"]
        tmap = d["meta"]["text_map"]
        cmap = d["meta"]["children_map"]
        blocks["page"] = Map({"ty": "page", "children": "pc"})
        cmap["pc"] = Array(["co", "mq", "tg"])
        tmap["c"] = Text("Heads up")
        blocks["co"] = Map(
            {
                "ty": "callout",
                "data": '{"icon":"⚠️"}',
                "external_id": "c",
                "children": "cc",
            }
        )
        cmap["cc"] = Array([])
        blocks["mq"] = Map(
            {"ty": "math_equation", "data": '{"formula":"a^2+b^2"}', "children": "mc"}
        )
        cmap["mc"] = Array([])
        tmap["t"] = Text("Details")
        blocks["tg"] = Map(
            {
                "ty": "toggle_list",
                "data": '{"level":3}',
                "external_id": "t",
                "children": "tc",
            }
        )
        cmap["tc"] = Array([])
    md = documents._doc_to_markdown(root["document"])
    assert "> [!WARNING]\n> Heads up" in md
    assert "$$\na^2+b^2\n$$" in md
    assert "### Details" in md


def test_page_mention_roundtrip():
    # forward: [label](mention:<id>) -> a "$" op carrying the page-mention attribute
    delta = documents._md_inline_to_delta("See [Home](mention:pg123) now")
    mention = next(o for o in delta if o.get("attributes", {}).get("mention"))
    assert mention["insert"] == "$"
    assert mention["attributes"]["mention"] == {"type": "page", "page_id": "pg123"}
    # reverse: the mention op renders back to the same Markdown link
    rendered = documents._inline_md(
        [("$", {"mention": {"type": "page", "page_id": "pg123"}})]
    )
    assert rendered == "[](mention:pg123)"
