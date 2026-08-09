import re
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    MofNCompleteColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .api import CourseAPI


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.strip()
    name = name[:200]
    return name


def _extract_course_id(materials_data: dict) -> str:
    return materials_data["elements"][0]["id"]


def _build_module_lookup(materials_data: dict) -> dict:
    lookup = {}
    for module in materials_data.get("linked", {}).get("onDemandCourseMaterialModules.v1", []):
        lookup[module["id"]] = {
            "name": module["name"],
            "slug": module.get("slug", module["id"]),
            "lessonIds": module.get("lessonIds", []),
        }
    return lookup


def _build_lesson_lookup(materials_data: dict) -> dict:
    lookup = {}
    for lesson in materials_data.get("linked", {}).get("onDemandCourseMaterialLessons.v1", []):
        lookup[lesson["id"]] = {
            "name": lesson["name"],
            "slug": lesson.get("slug", lesson["id"]),
            "elementIds": lesson.get("elementIds", []),
        }
    return lookup


def _build_item_lookup(materials_data: dict) -> dict:
    lookup = {}
    for item in materials_data.get("linked", {}).get("onDemandCourseMaterialItems.v2", []):
        lookup[item["id"]] = item
    return lookup


def _get_ordered_lectures(
    materials_data: dict,
    module_lookup: dict,
    lesson_lookup: dict,
    item_lookup: dict,
) -> list:
    elements = materials_data.get("elements", [])
    if not elements:
        return []
    ordered_module_ids = elements[0].get("moduleIds", [])
    if not ordered_module_ids:
        return []

    lectures = []
    for module_pos, module_id in enumerate(ordered_module_ids, 1):
        lesson_ids = module_lookup.get(module_id, {}).get("lessonIds", [])
        item_pos = 0
        for lesson_id in lesson_ids:
            element_ids = lesson_lookup.get(lesson_id, {}).get("elementIds", [])
            for element_id in element_ids:
                item = item_lookup.get(element_id)
                if item is None:
                    continue
                content_type = item.get("contentSummary", {}).get("typeName", "")
                if content_type != "lecture":
                    continue
                if item.get("isLocked", False):
                    continue
                item_pos += 1
                stamped = dict(item)
                stamped["_module_index"] = module_pos
                stamped["_lecture_index"] = item_pos
                lectures.append(stamped)
    return lectures


def _get_lecture_items(materials_data: dict) -> list:
    items = materials_data.get("linked", {}).get("onDemandCourseMaterialItems.v2", [])
    lectures = []
    for item in items:
        content_type = item.get("contentSummary", {}).get("typeName", "")
        if content_type != "lecture":
            continue
        if item.get("isLocked", False):
            continue
        lectures.append(item)
    return lectures


class TranscriptDownloader:
    def __init__(
        self,
        api: CourseAPI,
        output_dir: Path,
        language: str = "en",
        fmt: str = "txt",
        console: Console | None = None,
    ):
        self.api = api
        self.output_dir = output_dir
        self.language = language
        self.fmt = fmt
        self.console = console or Console()

    def _get_subtitle_url(self, video_data: dict) -> str | None:
        videos = video_data.get("linked", {}).get("onDemandVideos.v1", [])
        if not videos:
            return None

        video = videos[0]

        if self.fmt == "txt":
            subtitles = video.get("subtitlesTxt", {})
        else:
            subtitles = video.get("subtitles", {})

        return subtitles.get(self.language)

    def fetch_all_transcripts(self, course_slug: str) -> dict:
        c = self.console

        # ── Fetch course data ─────────────────────────────────────────
        with c.status("[bright_cyan]  Fetching course materials…[/bright_cyan]", spinner="dots"):
            materials = self.api.get_course_materials(course_slug)

        course_id = _extract_course_id(materials)
        module_lookup = _build_module_lookup(materials)
        lesson_lookup = _build_lesson_lookup(materials)
        item_lookup = _build_item_lookup(materials)
        lecture_items = _get_ordered_lectures(materials, module_lookup, lesson_lookup, item_lookup)
        if not lecture_items:
            lecture_items = _get_lecture_items(materials)  # fallback: unordered, no prefixes

        course_dir = self.output_dir / course_slug
        course_dir.mkdir(parents=True, exist_ok=True)

        # ── Course overview panel ─────────────────────────────────────
        info_table = Table.grid(padding=(0, 2))
        info_table.add_column(style="muted", justify="right")
        info_table.add_column(style="bold white")
        info_table.add_row("Course", course_slug)
        info_table.add_row("Lectures", str(len(lecture_items)))
        info_table.add_row("Language", self.language.upper())
        info_table.add_row("Format", self.fmt.upper())
        info_table.add_row("Output", str(course_dir))

        c.print(
            Panel(
                info_table,
                title="[brand]📋  Course Overview[/brand]",
                border_style="bright_cyan",
                padding=(1, 2),
            )
        )
        c.print()

        if not lecture_items:
            c.print("[warning]  ⚠  No lecture videos found in this course.[/warning]")
            return {"success": 0, "skipped": 0, "failed": 0, "total": 0}

        # ── Download with progress bar ────────────────────────────────
        stats = {"success": 0, "skipped": 0, "failed": 0, "total": len(lecture_items)}
        results: list[tuple[str, str, str]] = []  # (status_icon, name, detail)

        with Progress(
            SpinnerColumn(style="bright_cyan"),
            TextColumn("[bold]{task.description}[/bold]"),
            BarColumn(
                bar_width=30,
                style="dim white",
                complete_style="bright_cyan",
                finished_style="bright_green",
            ),
            MofNCompleteColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            console=c,
            transient=False,
        ) as progress:
            task = progress.add_task("  Downloading transcripts", total=stats["total"])

            for idx, item in enumerate(lecture_items, 1):
                item_id = item["id"]
                item_name = _sanitize_filename(item["name"])
                module_id = item.get("moduleId", "")

                module_info = module_lookup.get(module_id, {})
                module_slug = module_info.get("slug", f"module-{module_id}")

                module_index = item.get("_module_index")
                if module_index is not None:
                    module_dir = course_dir / f"{module_index:02d}_{module_slug}"
                else:
                    module_dir = course_dir / module_slug
                module_dir.mkdir(parents=True, exist_ok=True)

                # Fetch video data
                try:
                    video_data = self.api.get_lecture_video(course_id, item_id)
                except Exception as e:
                    results.append(("❌", item_name, f"[error]Failed to fetch video data: {e}[/error]"))
                    stats["failed"] += 1
                    progress.advance(task)
                    continue

                subtitle_url = self._get_subtitle_url(video_data)

                if not subtitle_url:
                    results.append(("⊘", item_name, f"[warning]No {self.language} {self.fmt} subtitles[/warning]"))
                    stats["skipped"] += 1
                    progress.advance(task)
                    continue

                # Download subtitle
                try:
                    subtitle_text = self.api.download_subtitle(subtitle_url)
                except Exception as e:
                    results.append(("❌", item_name, f"[error]Download failed: {e}[/error]"))
                    stats["failed"] += 1
                    progress.advance(task)
                    continue

                lecture_index = item.get("_lecture_index")
                if lecture_index is not None:
                    filename = f"{lecture_index:02d}_{item_name}.{self.fmt}"
                else:
                    filename = f"{item_name}.{self.fmt}"
                filepath = module_dir / filename
                filepath.write_text(subtitle_text, encoding="utf-8")

                rel_path = filepath.relative_to(self.output_dir)
                results.append(("✔", item_name, f"[muted]{rel_path}[/muted]"))
                stats["success"] += 1
                progress.advance(task)

        # ── Results tree ──────────────────────────────────────────────
        c.print()

        tree = Tree("[bold bright_cyan]📂  Results[/bold bright_cyan]")
        for icon, name, detail in results:
            if icon == "✔":
                style_icon = f"[bright_green]{icon}[/bright_green]"
            elif icon == "⊘":
                style_icon = f"[yellow]{icon}[/yellow]"
            else:
                style_icon = f"[red]{icon}[/red]"
            tree.add(f"{style_icon}  [bold]{name}[/bold]  {detail}")
        c.print(tree)

        # ── Summary panel ─────────────────────────────────────────────
        c.print()

        summary_parts = []
        if stats["success"]:
            summary_parts.append(f"[bright_green]✔ {stats['success']} downloaded[/bright_green]")
        if stats["skipped"]:
            summary_parts.append(f"[yellow]⊘ {stats['skipped']} skipped[/yellow]")
        if stats["failed"]:
            summary_parts.append(f"[red]✖ {stats['failed']} failed[/red]")

        summary_text = "   ".join(summary_parts)
        summary_text += f"\n\n[muted]Files saved to [bold]{course_dir}[/bold][/muted]"

        c.print(
            Panel(
                summary_text,
                title="[brand]✨  Summary[/brand]",
                border_style="bright_green" if not stats["failed"] else "yellow",
                padding=(1, 2),
            )
        )

        return stats
