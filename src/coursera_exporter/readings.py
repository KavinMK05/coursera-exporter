"""Reading (supplement) page extraction.

Coursera reading pages are stored as CML ("co-content" markup) and served by
``onDemandSupplements.v1``. The API response conveniently includes both the raw
CML (``definition.value``) and a server-rendered HTML version
(``definition.renderableHtmlWithMetadata.renderableHtml``), so we convert that
HTML — or the raw CML as a fallback — into Markdown using only the stdlib.

Embedded file attachments (PDFs, ZIPs, …) inside readings are downloadable via
the authenticated session and are saved next to the extracted text.
"""

import re
from html import escape as _html_escape
from html.parser import HTMLParser
from pathlib import Path

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    MofNCompleteColumn,
    TimeElapsedColumn,
)

from .video_downloader import _sanitize_filename

COURSERA_BASE = "https://www.coursera.org"

# assetType segment used in Coursera's asset download URLs, guessed from the
# file extension when the CML asset tag doesn't name it explicitly.
_EXT_TO_ASSET_TYPE = {
    "pdf": "pdf", "zip": "zip", "csv": "csv", "txt": "txt",
    "xls": "xls", "xlsx": "xls", "doc": "doc", "docx": "doc",
    "ppt": "presentation", "pptx": "presentation", "ipynb": "ipynb",
    "py": "py", "html": "html", "json": "json",
}


def _asset_download_url(asset_id: str, asset_type: str = "", extension: str = "") -> str:
    kind = (asset_type or "").lower() or _EXT_TO_ASSET_TYPE.get((extension or "").lower(), "generic")
    return f"{COURSERA_BASE}/api/rest/v1/asset/download/{kind}/{asset_id}"


# --------------------------------------------------------------------------- #
# CML → HTML tag stream renaming
# --------------------------------------------------------------------------- #
class _CMLToHTMLStream(HTMLParser):
    """Feed raw CML into an ``_HTMLToMarkdown`` by renaming CML tags to their
    HTML equivalents on the fly (heading→hN, text→p, list→ul/ol, …)."""

    def __init__(self, sink: "_HTMLToMarkdown"):
        super().__init__(convert_charrefs=True)
        self._sink = sink
        self._stack: list[tuple[str, str]] = []  # (original tag, renamed tag)

    def _rename(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        ad = {k.lower(): v for k, v in attrs}
        if tag == "heading":
            raw = ad.get("level", "2")
            try:
                level = max(1, min(6, int(str(raw))))
            except ValueError:
                level = 2
            return f"h{level}"
        if tag == "text":
            return "p"
        if tag == "list":
            bullet = (ad.get("bullettype") or ad.get("bulletType") or "bullets").lower()
            return "ol" if bullet in ("numbers", "numbered") else "ul"
        if tag == "co-content":
            return "div"
        return tag

    def handle_starttag(self, tag, attrs):
        mapped = self._rename(tag, attrs)
        self._stack.append((tag, mapped))
        self._sink.handle_starttag(mapped, attrs)

    def handle_startendtag(self, tag, attrs):
        if tag == "asset":
            self._sink.handle_startendtag("asset", attrs)
            return
        if tag in ("br", "img", "hr"):
            self._sink.handle_startendtag(tag, attrs)
            return
        mapped = self._rename(tag, attrs)
        self._sink.handle_starttag(mapped, attrs)
        self._sink.handle_endtag(mapped)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                while len(self._stack) > i:
                    _, mapped = self._stack.pop()
                    self._sink.handle_endtag(mapped)
                return
        # stray close tag — ignore

    def handle_data(self, data):
        self._sink.handle_data(data)


# --------------------------------------------------------------------------- #
# HTML → Markdown converter (stdlib only)
# --------------------------------------------------------------------------- #
class _HTMLToMarkdown(HTMLParser):
    """Event-driven converter for the small HTML subset Coursera's CML renderer
    emits: headings, paragraphs, nested lists, links, emphasis, tables, code
    blocks, images, and ``cml-asset`` attachment blocks."""

    _SKIP_TAGS = {"script", "style", "svg", "iframe", "noscript"}
    _INLINE_MARKS = {"strong": "**", "b": "**", "em": "*", "i": "*", "code": "`"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.buf: list[str] = []
        self.lists: list[dict] = []  # {"kind","indent","counter","in_li","marker"}
        self.bq = 0
        self.heading = 0
        self.pre = 0
        self.pre_lines: list[str] = []
        self.skip = 0
        self.rows: list[list[str]] | None = None
        self.cell: list[str] | None = None
        self.a_stack: list[str | None] = []
        self.pending_asset: dict | None = None
        self.assets: list[dict] = []

    # -- helpers ----------------------------------------------------------- #
    def _prefix(self) -> str:
        return "> " * self.bq

    def _norm(self, data: str, target: list[str]) -> str:
        text = re.sub(r"[ \t\r\n\f\v]+", " ", data)
        if not text:
            return ""
        if text == " ":
            if not target or target[-1].endswith(" ") or target[-1].endswith("\n"):
                return ""
            return " "
        if not target:
            text = text.lstrip(" ")
        return text

    def _flush(self, keep_blank: bool = True) -> None:
        text = "".join(self.buf).strip()
        self.buf = []
        if not text:
            return
        text = re.sub(r"(\*\*|[*`])\s+\1", "", text)  # drop empty emphasis artifacts
        for ln in text.split("\n"):
            ln = ln.strip()
            if ln:
                self.lines.append(self._prefix() + ln)
        if keep_blank:
            self.lines.append(self._prefix())

    def _emit_list_item(self, marker: str, indent: int) -> None:
        text = "".join(self.buf).strip()
        self.buf = []
        if not text:
            return
        text = re.sub(r"(\*\*|[*`])\s+\1", "", text)
        for i, ln in enumerate(text.split("\n")):
            ln = ln.strip()
            if ln:
                cont = " " * len(marker)
                self.lines.append((" " * indent) + (marker if i == 0 else cont) + ln)

    def _emit_table(self) -> None:
        rows, self.rows = self.rows, None
        if not rows:
            return
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]

        def esc(s: str) -> str:
            s = s.replace("|", "\\|").replace("\n", " ").strip()
            return s or " "

        self.lines.append("| " + " | ".join(esc(c) for c in rows[0]) + " |")
        self.lines.append("| " + " | ".join(["---"] * width) + " |")
        for r in rows[1:]:
            self.lines.append("| " + " | ".join(esc(c) for c in r) + " |")
        self.lines.append("")

    def _finalize_asset(self) -> None:
        pa, self.pending_asset = self.pending_asset, None
        if not pa:
            return
        name = (pa.get("name") or pa.get("info") or "").strip() or "attachment"
        href = pa.get("href")
        if not href and pa.get("id"):
            # Fall back to constructing the download URL from data attributes.
            ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
            href = _asset_download_url(pa["id"], pa.get("asset_type") or "", ext)
        if href:
            self.assets.append({"name": name, "url": href})
            self.buf.append(f"[📄 {name}]({href})")
        else:
            self.buf.append(f"📄 {name}")

    # -- tag dispatch ------------------------------------------------------- #
    def handle_starttag(self, tag, attrs, self_closing: bool = False):
        if self.skip:
            if tag in self._SKIP_TAGS:
                self.skip += 1
            return
        if tag in self._SKIP_TAGS:
            self.skip = 1
            return

        if tag == "asset":
            self._on_asset(attrs)
            return
        if tag == "img":
            self._on_img(attrs)
            return
        if tag == "br":
            self.buf.append(" ")
            return
        if tag == "hr":
            self._flush()
            self.lines.extend([self._prefix() + "---", self._prefix()])
            return

        if self.pre:  # inside <pre>: ignore structure
            if tag == "pre":
                self.pre += 1
            return

        if tag == "a":
            href = dict(attrs).get("href")
            if self.pending_asset is not None and self.pending_asset.get("href") is None:
                self.pending_asset["href"] = href  # capture download link, hide its text
                self.a_stack.append(None)
            else:
                self.buf.append("[")
                self.a_stack.append(href)
            return

        if self.pending_asset is not None:
            if tag == "div":
                self.pending_asset["depth"] = self.pending_asset.get("depth", 1) + 1
            return  # suppress structure inside asset blocks

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush()
            self.heading = int(tag[1])
            return
        if tag == "p":
            if self.in_cell:
                return
            self._flush()
            return
        if tag in ("div", "section", "article", "figure"):
            cls = (dict(attrs).get("class") or "")
            if tag == "div" and "cml-asset" in cls:
                a = dict(attrs)
                self._flush()
                self.pending_asset = {
                    "name": a.get("data-name") or "",
                    "href": None,
                    "id": a.get("data-id") or "",
                    "asset_type": a.get("data-asset-type") or "",
                    "depth": 1,
                }
                return
            self._flush()
            return
        if tag == "figcaption":
            self._flush()
            return
        if tag == "blockquote":
            self._flush()
            self.bq += 1
            return
        if tag == "pre":
            self._flush()
            self.pre = 1
            self.pre_lines = []
            self.lines.append("```")
            return
        if tag in ("ul", "ol") and not self.in_cell:
            if self.lists:
                top = self.lists[-1]
                if top["in_li"]:
                    self._emit_list_item(top["marker"], top["indent"])
            else:
                self._flush()
                self.lines.append(self._prefix())
            parent_indent = self.lists[-1]["indent"] if self.lists else 0
            extra = 2 if tag == "ul" else 3
            self.lists.append({
                "kind": tag, "indent": parent_indent + extra, "counter": 0,
                "in_li": False, "marker": "- " if tag == "ul" else "",
            })
            return
        if tag == "li" and self.lists:
            top = self.lists[-1]
            if top["in_li"]:
                self._emit_list_item(top["marker"], top["indent"])
            top["in_li"] = True
            if top["kind"] == "ol":
                top["counter"] += 1
                top["marker"] = f"{top['counter']}. "
            return
        if tag == "table" and not self.in_cell:
            self._flush()
            self.rows = []
            return
        if tag == "tr" and self.rows is not None:
            self.rows.append([])
            return
        if tag in ("td", "th") and self.rows is not None:
            self.cell = []
            return
        if tag in self._INLINE_MARKS:
            self.buf.append(self._INLINE_MARKS[tag])
            return

    def handle_endtag(self, tag):
        if self.skip:
            if tag in self._SKIP_TAGS:
                self.skip -= 1
            return
        if tag == "a" and self.a_stack:
            href = self.a_stack.pop()
            if href is None and self.pending_asset is not None:
                return  # download-capture anchor — no inline output
            self.buf.append(f"]({href})" if href else "]")
            return
        if self.pending_asset is not None and tag in ("div", "p", "span"):
            if tag == "div":
                pa = self.pending_asset
                pa["depth"] = pa.get("depth", 1) - 1
                if pa["depth"] <= 0:
                    self._finalize_asset()
            return
        if self.pre:
            if tag == "pre":
                self.pre = 0
                raw = "".join(self.pre_lines).strip("\n")
                self.lines.extend(raw.split("\n") if raw else [])
                self.lines.append("```")
                self.lines.append("")
                self.pre_lines = []
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = "".join(self.buf).strip()
            self.buf = []
            if text:
                self.lines.extend([self._prefix() + ("#" * self.heading) + " " + text, self._prefix()])
            self.heading = 0
            return
        if tag == "p" and not self.in_cell:
            if not (self.lists and self.lists[-1]["in_li"]):
                self._flush()
            return
        if tag in ("div", "section", "article", "figure", "figcaption"):
            self._flush()
            return
        if tag == "blockquote":
            self._flush()
            self.bq = max(0, self.bq - 1)
            self.lines.append(self._prefix())
            return
        if tag in ("ul", "ol") and self.lists:
            top = self.lists[-1]
            if top["kind"] == tag:
                if top["in_li"]:
                    self._emit_list_item(top["marker"], top["indent"])
                    top["in_li"] = False
                self.lists.pop()
                if not self.lists:
                    self.lines.append(self._prefix())
            return
        if tag == "li" and self.lists and self.lists[-1]["in_li"]:
            top = self.lists[-1]
            self._emit_list_item(top["marker"], top["indent"])
            top["in_li"] = False
            return
        if tag == "table" and self.rows is not None:
            self._emit_table()
            return
        if tag in ("td", "th") and self.cell is not None and self.rows:
            self.rows[-1].append("".join(self.cell).strip())
            self.cell = None
            return
        if tag in self._INLINE_MARKS:
            self.buf.append(self._INLINE_MARKS[tag])
            return

    def handle_startendtag(self, tag, attrs):
        if tag in ("asset", "img", "br", "hr"):
            self.handle_starttag(tag, attrs)
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if self.skip:
            return
        if self.pre:
            self.pre_lines.append(data)
            return
        if self.pending_asset is not None:
            name = data.strip()
            if name and not self.pending_asset.get("info"):
                self.pending_asset["info"] = name
            return
        target = self.cell if self.cell is not None else self.buf
        target.append(self._norm(data, target))

    # -- result -------------------------------------------------------------- #
    def result(self) -> tuple[str, list[dict]]:
        if self.rows is not None:
            self._emit_table()
        if self.pre:
            raw = "".join(self.pre_lines).strip("\n")
            if raw:
                self.lines.extend(raw.split("\n"))
            self.lines.append("```")
            self.pre = 0
        self._flush(keep_blank=False)
        md = "\n".join(self.lines)
        md = re.sub(r"\n{3,}", "\n\n", md).strip()
        return md, self.assets

    @property
    def in_cell(self) -> bool:
        return self.cell is not None

    def _on_img(self, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        src = a.get("src") or ""
        alt = a.get("alt") or ""
        target = self.cell if self.cell is not None else self.buf
        if src:
            target.append(f"![{alt}]({src})")

    def _on_asset(self, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        asset_id = a.get("id") or a.get("assetId") or ""
        name = a.get("name") or "attachment"
        ext = (a.get("extension") or "").lower()
        if ext and not name.lower().endswith("." + ext):
            name = f"{name}.{ext}"
        url = _asset_download_url(asset_id, a.get("assetType") or "", ext)
        self.assets.append({"name": name, "url": url})
        target = self.cell if self.cell is not None else self.buf
        target.append(f"[📄 {name}]({url})")


def extract_markdown(html: str | None = None, cml: str | None = None) -> tuple[str, list[dict]]:
    """Convert Coursera reading content to Markdown.

    Prefers the server-rendered ``renderableHtml``; falls back to raw CML.
    Returns ``(markdown, assets)`` where ``assets`` is a list of
    ``{"name", "url"}`` file attachments referenced by the reading.
    """
    conv = _HTMLToMarkdown()
    if html:
        conv.feed(html)
        conv.close()
    elif cml:
        stream = _CMLToHTMLStream(conv)
        stream.feed(cml)
        stream.close()
    return conv.result()


def _wrap_html_doc(title: str, body_html: str) -> str:
    return (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{_html_escape(title)}</title>\n"
        "<style>\n"
        "  body { font-family: Georgia, 'Times New Roman', serif; line-height: 1.6;"
        " color: #1a1a1a; max-width: 800px; margin: 2rem auto; padding: 0 1rem; }\n"
        "  table { border-collapse: collapse; margin: 1rem 0; }\n"
        "  td, th { border: 1px solid #bbb; padding: 6px 12px; }\n"
        "  img { max-width: 100%; }\n"
        "  pre { background: #f5f5f5; padding: 12px; overflow-x: auto; }\n"
        "</style>\n"
        f"</head>\n<body>\n{body_html}\n</body>\n</html>\n"
    )


# --------------------------------------------------------------------------- #
# Downloader
# --------------------------------------------------------------------------- #
class ReadingDownloader:
    """Downloads reading (supplement) pages: text as Markdown + HTML, plus any
    file attachments embedded in the reading, into per-reading folders."""

    def __init__(self, api, console: Console | None = None):
        self.api = api
        self.console = console or Console()

    def _download_assets(self, assets: list[dict], reading_dir: Path) -> tuple[int, int]:
        ok = failed = 0
        for asset in assets:
            name = _sanitize_filename(asset["name"]) or "attachment"
            url = asset["url"]
            m = re.search(r"/asset/download/([a-zA-Z0-9]+)/", url)
            ext = m.group(1).lower() if m else ""
            if ext and not Path(name).suffix:
                name = f"{name}.{ext}"
            dest = reading_dir / name
            try:
                if dest.exists():
                    ok += 1
                    continue
                self.api.download_file(url, dest)
                ok += 1
            except Exception:  # noqa: BLE001
                failed += 1
        return ok, failed

    def _process_one(self, job: dict) -> tuple[str, str, str]:
        name = job["display_name"]
        reading_dir: Path = job["dir"]
        base = job["file_base"]
        try:
            supp = self.api.get_supplement(job["course_id"], job["item_id"])
        except Exception as e:  # noqa: BLE001
            if "404" in str(e):
                return ("⊘", name, "[warning]No text content (not a reading page)[/warning]")
            return ("❌", name, f"[error]Failed: {e}[/error]")

        assets = supp.get("linked", {}).get("openCourseAssets.v1", []) or []
        html_parts: list[str] = []
        cml_parts: list[str] = []
        for entry in assets:
            definition = entry.get("definition", {}) or {}
            meta = definition.get("renderableHtmlWithMetadata") or {}
            renderable = meta.get("renderableHtml")
            if renderable:
                html_parts.append(renderable)
            elif definition.get("value"):
                cml_parts.append(definition["value"])
        html = "\n".join(html_parts).strip()
        cml = "\n".join(cml_parts).strip()

        if not html and not cml:
            return ("⊘", name, "[warning]No text content (not a reading page)[/warning]")

        reading_dir.mkdir(parents=True, exist_ok=True)
        md_path = reading_dir / f"{base}.md"
        html_path = reading_dir / f"{base}.html"
        if md_path.exists() and html_path.exists():
            return ("⊘", name, "[yellow]Already exists[/yellow]")

        try:
            body, embedded = extract_markdown(html or None, cml or None)
            md_text = f"# {name}\n\n{body}".strip() + "\n"
            md_path.write_text(md_text, encoding="utf-8")
            doc = _wrap_html_doc(name, html if html else f"<pre>{_html_escape(cml)}</pre>")
            html_path.write_text(doc, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            return ("❌", name, f"[error]Conversion failed: {e}[/error]")

        ok, failed = self._download_assets(embedded, reading_dir)
        detail = f"[muted]{reading_dir.name}/{base}.md[/muted]"
        if ok:
            detail += f" [muted]+ {ok} file(s)[/muted]"
        if failed:
            detail += f" [warning]({failed} file(s) failed)[/warning]"
        return ("✔", name, detail)

    def run(self, jobs: list[dict], progress: Progress | None = None) -> dict:
        """``jobs``: list of ``{"display_name", "file_base", "dir", "item_id", "course_id"}``."""
        stats = {"success": 0, "skipped": 0, "failed": 0, "total": len(jobs)}
        results: list[tuple[str, str, str]] = []
        task = None
        if progress is not None:
            task = progress.add_task("  Extracting readings", total=stats["total"])
        for job in jobs:
            icon, name, detail = self._process_one(job)
            if icon == "✔":
                stats["success"] += 1
            elif icon == "⊘":
                stats["skipped"] += 1
            else:
                stats["failed"] += 1
            results.append((icon, name, detail))
            if task is not None:
                progress.advance(task)
        return {"stats": stats, "results": results}