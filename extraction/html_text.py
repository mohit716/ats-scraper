import re

from lxml import html as lxml_html

# Removed before any text extraction: these never carry job description prose,
# and they inflate the LLM prompt.
DROP_TAGS = ["script", "style", "noscript", "svg", "iframe", "template"]

BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "br", "tr",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "blockquote",
}


def _clean_tree(fragment):
    for tag in DROP_TAGS:
        for node in fragment.xpath(f".//{tag}"):
            node.getparent().remove(node)
    return fragment


def html_to_text(html_source):
    """Flatten HTML to readable plain text, preserving line and list structure."""
    if not html_source or not html_source.strip():
        return ""

    try:
        tree = lxml_html.fromstring(html_source)
    except Exception:
        return ""

    tree = _clean_tree(tree)

    parts = []
    for node in tree.iter():
        tag = node.tag if isinstance(node.tag, str) else ""
        if tag == "li":
            text = (node.text or "").strip()
            if text:
                parts.append(f"\n- {text}")
            continue
        if tag in BLOCK_TAGS:
            parts.append("\n")
        if node.text and node.text.strip():
            parts.append(node.text.strip())
        if node.tail and node.tail.strip():
            parts.append(node.tail.strip())

    text = " ".join(parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize(text):
    """Lowercase word sequence, for comparing two extractions of the same page."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())
