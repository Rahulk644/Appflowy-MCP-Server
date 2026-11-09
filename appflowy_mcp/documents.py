"""Markdown, block-tree and document CRDT conversion without network access."""

import json

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins.dollarmath import dollarmath_plugin
from pycrdt import Array, Map, Text

from .collab import _nid

# ---- Markdown → AppFlowy block tree ---------------------------------------
# AppFlowy Cloud converts Markdown → blocks server-side for ROW bodies, but the
# page-view create endpoint only accepts a structured block tree. Parse Markdown
# with markdown-it's CommonMark parser and emit the block tree supplied to AppFlowy —
# one Markdown content interface everywhere. Covers the basic-block palette;
# unknown constructs fall back to a paragraph so text is never silently dropped.
# Tables fall back to text; columns require a separate structural workflow.

# dollarmath is configured with allow_digits/allow_space OFF, which is a data-loss
# fix, not a preference. With the defaults, any prose containing two dollar AMOUNTS
# has everything between them swallowed into a math node:
#   "ARR hit $560k this quarter, up from $380k last year."
#     -> "ARR hit 380k last year."          <- figures and words silently gone
# Money in notes is far more common than inline TeX, and disallowing a digit or a
# space adjacent to the delimiter kills the money case while keeping real math:
# "$e^{i\pi}+1=0$" still parses, and $$...$$ block math is untouched.
_md_parser = (
    MarkdownIt("commonmark")
    .enable(["table", "strikethrough"])
    .use(dollarmath_plugin, allow_digits=False, allow_space=False)
)

# GFM alert types (> [!NOTE]) <-> AppFlowy callout icons, for round-tripping callouts.
_ALERT_ICONS = {
    "note": "📝",
    "tip": "💡",
    "important": "❗",
    "warning": "⚠️",
    "caution": "🔥",
}
_ICON_ALERTS = {v: k for k, v in _ALERT_ICONS.items()}

_INLINE_ATTR = {"strong": "bold", "em": "italic", "s": "strikethrough"}
_TASK_PREFIXES = {"[ ] ": False, "[x] ": True, "[X] ": True}


def _delta_op(text: str, attrs: dict) -> dict:
    op = {"insert": text}
    if attrs:
        op["attributes"] = dict(attrs)
    return op


def _inline_delta(node) -> list:
    """A markdown-it 'inline' node -> AppFlowy delta (list of insert ops)."""
    ops: list = []

    def walk(children, attrs):
        for c in children:
            t = c.type
            if t == "text":
                if c.content:
                    ops.append(_delta_op(c.content, attrs))
            elif t in ("softbreak", "hardbreak"):
                ops.append(_delta_op("\n", attrs))
            elif t == "code_inline":
                ops.append(_delta_op(c.content, {**attrs, "code": True}))
            elif t in _INLINE_ATTR:
                walk(c.children, {**attrs, _INLINE_ATTR[t]: True})
            elif t == "link":
                href = c.attrs.get("href", "")
                if href.startswith("mention:"):  # [](mention:<page_id>) -> page mention
                    ops.append(
                        {
                            "insert": "$",
                            "attributes": {
                                "mention": {"type": "page", "page_id": href[8:]}
                            },
                        }
                    )
                else:
                    walk(c.children, {**attrs, "href": href})
            elif t == "image":
                alt = c.content or c.attrs.get("alt", "")
                if alt:
                    ops.append(_delta_op(alt, attrs))
            elif t == "math_inline":
                ops.append(_delta_op(f"${c.content}$", attrs))
            elif c.children:
                walk(c.children, attrs)
            elif c.content:
                ops.append(_delta_op(c.content, attrs))

    walk(node.children, {})
    return ops


def _first_inline(node):
    for c in node.children:
        if c.type == "inline":
            return c
    return None


def _delta_of(node) -> list:
    inl = _first_inline(node)
    return _inline_delta(inl) if inl else []


def _sole_image_url(para_node):
    """If a paragraph is a lone image, return its src (AppFlowy image is a block,
    not inline); else None."""
    inl = _first_inline(para_node)
    if not inl:
        return None
    imgs = [c for c in inl.children if c.type == "image"]
    other = [
        c
        for c in inl.children
        if c.type not in ("image", "softbreak", "hardbreak")
        and (c.content or c.children)
    ]
    return imgs[0].attrs.get("src", "") if len(imgs) == 1 and not other else None


def _task_state(delta):
    """If the delta starts with a GFM task marker, return (checked, stripped_delta);
    else None."""
    if not delta or "attributes" in delta[0]:
        return None
    lead_ops, lead = 0, ""
    for o in delta:
        if "attributes" in o:
            break
        lead += o["insert"]
        lead_ops += 1
    for pref, checked in _TASK_PREFIXES.items():
        if lead.startswith(pref):
            remainder = lead[len(pref) :]
            rest = delta[lead_ops:]
            new = ([{"insert": remainder}] if remainder else []) + [
                dict(o) for o in rest
            ]
            return checked, (new or [{"insert": ""}])
    return None


def _node_plaintext(node) -> str:
    if node.type in ("fence", "code_block"):
        return node.content.rstrip("\n")
    if not node.children:
        return node.content or ""
    return "".join(_node_plaintext(c) for c in node.children)


def _drop_first_line(delta) -> list:
    """Remove the first text line (through the first newline) from a delta — strips the
    "[!NOTE]" marker line off a GFM alert before the rest becomes the callout body."""
    out, dropping = [], True
    for op in delta:
        if not dropping:
            out.append(op)
            continue
        nl = op["insert"].find("\n")
        if nl == -1:
            continue  # whole op is on the first line -> drop it
        dropping = False
        rest = op["insert"][nl + 1 :]
        if rest:
            out.append({**op, "insert": rest})
    return out


def _list_item_block(li, list_type):
    delta, children = [], []
    for c in li.children:
        if c.type == "paragraph" and not delta and not children:
            delta = _delta_of(c)
        else:
            children.extend(_block_from_node(c))
    task = _task_state(delta)
    if task is not None:
        block = {"type": "todo_list", "data": {"checked": task[0], "delta": task[1]}}
    else:
        block = {"type": list_type, "data": {"delta": delta or [{"insert": ""}]}}
    if children:
        block["children"] = children
    return block


def _block_from_node(node) -> list:
    """Map one markdown-it block node -> zero or more AppFlowy blocks."""
    t = node.type
    if t == "heading":
        lvl = min(max(int(node.tag[1:]), 1), 6)
        return [{"type": "heading", "data": {"level": lvl, "delta": _delta_of(node)}}]
    if t == "paragraph":
        url = _sole_image_url(node)
        if url:
            return [{"type": "image", "data": {"url": url}}]
        return [{"type": "paragraph", "data": {"delta": _delta_of(node)}}]
    if t == "hr":
        return [{"type": "divider", "data": {}}]
    if t in ("fence", "code_block"):
        lang = (node.info or "").strip().split(" ")[0] if t == "fence" else ""
        code = node.content.rstrip("\n")
        return [
            {"type": "code", "data": {"language": lang, "delta": [{"insert": code}]}}
        ]
    if t == "math_block":
        return [{"type": "math_equation", "data": {"formula": node.content.strip()}}]
    if t == "blockquote":
        parts = [_delta_of(c) for c in node.children if c.type == "paragraph"]
        delta = []
        for i, p in enumerate(parts):
            if i:
                delta.append({"insert": "\n"})
            delta.extend(p)
        # A GFM alert ("> [!NOTE]") becomes an AppFlowy callout; else a plain quote.
        lead = delta[0]["insert"] if delta and "attributes" not in delta[0] else ""
        marker = lead.split("\n", 1)[0].strip().lower()
        for name, icon in _ALERT_ICONS.items():
            if marker == f"[!{name}]":
                body = _drop_first_line(delta)
                return [
                    {
                        "type": "callout",
                        "data": {"icon": icon, "delta": body or [{"insert": ""}]},
                    }
                ]
        return [{"type": "quote", "data": {"delta": delta or [{"insert": ""}]}}]
    if t == "bullet_list":
        return [_list_item_block(li, "bulleted_list") for li in node.children]
    if t == "ordered_list":
        return [_list_item_block(li, "numbered_list") for li in node.children]
    text = _node_plaintext(node)
    return (
        [{"type": "paragraph", "data": {"delta": [{"insert": text}]}}] if text else []
    )


def _md_to_blocks(markdown: str) -> list:
    """Parse Markdown into an AppFlowy page block-tree (list of block dicts)."""
    tree = SyntaxTreeNode(_md_parser.parse(markdown or ""))
    blocks: list = []
    for node in tree.children:
        blocks.extend(_block_from_node(node))
    return blocks


# ---- AppFlowy block tree → Markdown (the inverse of _md_to_blocks) ---------
# Reads a document collab's blocks and renders Markdown, so an agent can pull a
# page or card body back out in the format it writes (symmetric with
# create_page(markdown=...)). Inline styles come from each yjs Text's diff() —
# segments of (text, {bold|italic|strikethrough|code|href}); block-type fields
# (level, checked, language, url) come from the block's `data` JSON.

# Markdown list "family": bullet-style items (- / - [ ]) pack tight together, but a
# switch to/from an ordered (1.) list needs a blank line so it re-parses cleanly.
_LIST_FAMILY = {"bulleted_list": "ul", "todo_list": "ul", "numbered_list": "ol"}


def _inline_md(delta) -> str:
    out = []
    for text, attrs in delta or []:
        a = attrs or {}
        mention = a.get("mention")
        if mention and mention.get("page_id"):  # page mention -> [](mention:<id>)
            out.append(f"[](mention:{mention['page_id']})")
            continue
        if a.get("code"):
            seg = f"`{text}`"
        else:
            seg = text
            if a.get("bold"):
                seg = f"**{seg}**"
            if a.get("italic"):
                seg = f"*{seg}*"
            if a.get("strikethrough"):
                seg = f"~~{seg}~~"
        if a.get("href"):
            seg = f"[{seg}]({a['href']})"
        out.append(seg)
    return "".join(out)


def _render_block(bid, blocks, cmap, tmap, depth):
    """Return (lines, is_list_item) for a block and its (indented) children."""
    b = blocks[bid]
    ty = b.get("ty", "")
    data = json.loads(b["data"]) if (b.get("data")) else {}
    ext = b.get("external_id", None)
    delta = tmap[ext].diff() if (ext is not None and ext in tmap) else []
    pad = "  " * depth

    if ty == "code":
        raw = "".join(t for t, _ in delta)
        lines = [f"```{data.get('language', '')}", *raw.split("\n"), "```"]
    elif ty == "divider":
        lines = ["---"]
    elif ty == "image":
        lines = [f"![]({data.get('url', '')})"]
    elif ty == "math_equation":
        lines = ["$$", data.get("formula", ""), "$$"]
    else:
        text = _inline_md(delta)
        if ty == "heading":
            lines = ["#" * int(data.get("level", 1)) + " " + text]
        elif ty == "bulleted_list":
            lines = [f"{pad}- {text}"]
        elif ty == "numbered_list":
            lines = [f"{pad}1. {text}"]
        elif ty == "todo_list":
            box = "x" if data.get("checked") else " "
            lines = [f"{pad}- [{box}] {text}"]
        elif ty == "quote":
            lines = [f"> {text}"]
        elif ty == "callout":
            alert = _ICON_ALERTS.get(data.get("icon", ""))
            head = f"> [!{alert.upper()}]" if alert else "> [!NOTE]"
            body = text.split("\n") if text else []
            if not alert and data.get("icon") and body:
                body[0] = f"{data['icon']} {body[0]}"
            lines = [head] + [f"> {ln}" for ln in body]
        elif ty == "toggle_list":  # a level makes it a toggle-heading; no md toggle
            lvl = data.get("level")
            lines = ["#" * int(lvl) + " " + text] if lvl else [f"{pad}- {text}"]
        else:  # paragraph, and any unknown block -> plain text (never dropped)
            lines = [text]

    ck = b.get("children", None)
    if ck is not None and ck in cmap:
        for c in list(cmap[ck]):
            child_lines, _ = _render_block(c, blocks, cmap, tmap, depth + 1)
            lines.extend(child_lines)
    return lines, _LIST_FAMILY.get(ty)


def _doc_to_markdown(document) -> str:
    """Render a document map ({blocks, meta, page_id}) to Markdown."""
    blocks, meta = document["blocks"], document["meta"]
    cmap, tmap = meta["children_map"], meta["text_map"]
    root = blocks[document["page_id"]]
    ck = root.get("children", None)
    if ck is None or ck not in cmap:
        return ""
    parts, prev_fam = [], None
    for i, c in enumerate(list(cmap[ck])):
        lines, fam = _render_block(c, blocks, cmap, tmap, 0)
        block_md = "\n".join(lines)
        if i == 0:
            parts.append(block_md)
        else:
            parts.append(("\n" if fam and fam == prev_fam else "\n\n") + block_md)
        prev_fam = fam
    return "".join(parts).strip() + "\n"


def _delete_block_tree(blocks, children_map, text_map, block_id: str) -> None:
    block = blocks[block_id]
    children_key = block.get("children", None)
    if children_key is not None and children_key in children_map:
        for child_id in list(children_map[children_key]):
            _delete_block_tree(blocks, children_map, text_map, child_id)
        del children_map[children_key]
    ext = block.get("external_id", None)
    if ext is not None and ext in text_map:
        del text_map[ext]
    del blocks[block_id]


# Code / equation blocks hold literal text; everything else renders inline Markdown.
_PLAIN_TEXT_TYS = {"code", "math_equation"}


def _md_inline_to_delta(text: str) -> list:
    """Parse one line of inline Markdown (**bold**, *italic*, `code`, ~~strike~~,
    [links](url)) into an AppFlowy delta; literal fallback for non-inline input."""
    if not text:
        return []
    blocks = _md_to_blocks(text)
    if len(blocks) == 1 and blocks[0]["type"] == "paragraph":
        return blocks[0]["data"]["delta"]
    return [{"insert": text}]


def _set_text(text_obj, delta) -> None:
    """Overwrite a yjs Text from a delta: plain content, then inline formatting ranges
    (bold/italic/strikethrough/code/href) via Text.format(start, stop). Offsets are in
    UTF-8 BYTES — pycrdt/yrs indexes Text by byte, so a multi-byte char (an emoji is 4
    bytes) must advance the position by its byte length or the format range drifts past
    it (e.g. a leading emoji would mis-place every link on the line)."""
    if len(text_obj) > 0:
        del text_obj[0 : len(text_obj)]
    plain = "".join(op["insert"] for op in delta)
    if plain:
        text_obj.insert(0, plain)
    pos = 0
    for op in delta:
        n = len(op["insert"].encode("utf-8"))
        attrs = op.get("attributes")
        if attrs and n:
            text_obj.format(pos, pos + n, attrs)
        pos += n


def _insert_pd_block(bmap, cmap, tmap, spec, parent_id) -> str:
    """Insert one page_data block dict (from _md_to_blocks) into a document's collab
    maps, recursively for its children; return the new block id. The inline text
    (data['delta']) moves to the text_map; the rest of data stays on the block. Callers
    append the returned id to the parent's children array. Must run inside a doc
    transaction."""
    bid, ckey = _nid(), _nid()
    data = dict(spec.get("data") or {})
    delta = data.pop("delta", None)
    block = {
        "id": bid,
        "ty": spec["type"],
        "parent": parent_id,
        "children": ckey,
        "data": json.dumps(data),
    }
    cmap[ckey] = Array([])
    if delta is not None:
        ext = _nid()
        block["external_id"] = ext
        block["external_type"] = "text"
        tmap[ext] = Text("")
        _set_text(tmap[ext], delta)
    bmap[bid] = Map(block)
    for child in spec.get("children") or []:
        cmap[ckey].append(_insert_pd_block(bmap, cmap, tmap, child, bid))
    return bid
