import re
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
from rich.tree import Tree

from .api import CourseAPI, parse_asset_items
from .video_downloader import VideoDownloader, AssetDownloader, _sanitize_filename


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


def _extract_course_id(materials_data: dict) -> str:
    return materials_data["elements"][0]["id"]


def _ordered_module_ids(materials_data: dict) -> list:
    """Return module IDs in course order.

    Prefer the explicit ordering from ``elements[0].moduleIds``. Real Coursera
    responses often omit ``moduleIds``, so fall back to the order the modules
    appear in the linked list (the API returns these in course order)."""
    elements = materials_data.get("elements", [])
    if elements:
        ids = elements[0].get("moduleIds") or []
        if ids:
            return list(ids)
    return [
        m["id"]
        for m in materials_data.get("linked", {}).get("onDemandCourseMaterialModules.v1", [])
        if m.get("id")
    ]


def _get_ordered_lectures(
    materials_data: dict,
    module_lookup: dict,
    lesson_lookup: dict,
    item_lookup: dict,
) -> list:
    elements = materials_data.get("elements", [])
    if not elements:
        return []
    ordered_module_ids = _ordered_module_ids(materials_data)
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
    """Fallback lecture ordering used when the module→lesson→element chain is
    unavailable (real Coursera responses often omit ``lessonIds``).

    Items are returned in the order the API provides them (course order), and
    each is stamped with a module index (from the ordered module list) and a
    per-module lecture index so output folders get consistent numbering.
    """
    module_pos = {
        mid: i for i, mid in enumerate(_ordered_module_ids(materials_data), 1)
    }
    per_module_counter: dict[str, int] = {}
    items = materials_data.get("linked", {}).get("onDemandCourseMaterialItems.v2", [])
    lectures = []
    for item in items:
        content_type = item.get("contentSummary", {}).get("typeName", "")
        if content_type != "lecture":
            continue
        if item.get("isLocked", False):
            continue
        mid = item.get("moduleId", "")
        m_index = module_pos.get(mid)
        if m_index is not None:
            per_module_counter[mid] = per_module_counter.get(mid, 0) + 1
            lec_index = per_module_counter[mid]
        else:
            lec_index = None
        stamped = dict(item)
        stamped["_module_index"] = m_index
        stamped["_lecture_index"] = lec_index
        lectures.append(stamped)
    return lectures


def _lecture_dir(module_dir: Path, lecture_index: int | None, lecture_name: str) -> Path:
    if lecture_index is not None:
        return module_dir / f"{lecture_index:02d}_{lecture_name}"
    return module_dir / lecture_name


def _module_index_for(materials_data: dict, module_id: str) -> int | None:
    """Return the 1-based position of ``module_id`` in the course's ordered
    module list, or ``None`` when it can't be determined."""
    try:
        return _ordered_module_ids(materials_data).index(module_id) + 1
    except (ValueError, AttributeError):
        return None


def _build_asset_jobs(materials_data: dict, module_lookup: dict, course_dir: Path) -> list:
    jobs = []
    for asset in parse_asset_items(materials_data):
        module_id = asset.get("module_id", "")
        module_info = module_lookup.get(module_id, {})
        slug = module_info.get("slug", module_id)
        # Match the indexed module folder used for lectures (e.g. 01_introduction-to-ml)
        # so assets nest under the same directory instead of a parallel one.
        mod_index = _module_index_for(materials_data, module_id)
        if module_info and mod_index is not None:
            module_dir = course_dir / f"{mod_index:02d}_{slug}"
        elif module_info:
            module_dir = course_dir / slug
        else:
            module_dir = course_dir / _sanitize_filename(asset["item_name"])
        asset_dir = module_dir / _sanitize_filename(asset["item_name"])
        jobs.append((asset["item_name"], asset["url"], asset_dir))
    return jobs


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

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def fetch_all_transcripts(self, course_slug: str) -> dict:
        """Backward-compatible helper: export transcripts only."""
        return self.export(course_slug, enabled={"transcripts"})

    def export(self, course_slug: str, enabled: set[str], quality: str = "best") -> dict:
        c = self.console
        enabled = set(enabled)
        wants_lectures = "transcripts" in enabled or "videos" in enabled

        # ── Fetch course data ─────────────────────────────────────────
        with c.status("[bright_cyan]  Fetching course materials…[/bright_cyan]", spinner="dots"):
            materials = self.api.get_course_materials(course_slug)

        course_id = _extract_course_id(materials)
        module_lookup = _build_module_lookup(materials)
        lesson_lookup = _build_lesson_lookup(materials)
        item_lookup = _build_item_lookup(materials)
        lecture_items = _get_ordered_lectures(materials, module_lookup, lesson_lookup, item_lookup)
        if not lecture_items:
            lecture_items = _get_lecture_items(materials)

        course_dir = self.output_dir / course_slug
        course_dir.mkdir(parents=True, exist_ok=True)

        # ── Overview panel ───────────────────────────────────────────
        self._show_overview(course_slug, lecture_items, enabled, quality, course_dir)

        if wants_lectures and not lecture_items:
            c.print("[warning]  ⚠  No lecture videos found in this course.[/warning]")
            return self._empty_stats(enabled)

        stats: dict[str, dict] = {k: self._zero_stats() for k in enabled}
        results: dict[str, list] = {k: [] for k in enabled}

        # ── Lecture loop (transcripts + queue videos) ───────────────
        video_jobs: list = []
        if wants_lectures and lecture_items:
            with Progress(
                SpinnerColumn(style="bright_cyan"),
                TextColumn("[bold]{task.description}[/bold]"),
                BarColumn(bar_width=30, style="dim white", complete_style="bright_cyan", finished_style="bright_green"),
                MofNCompleteColumn(),
                TextColumn("•"),
                TimeElapsedColumn(),
                console=c,
                transient=False,
            ) as progress:
                task = progress.add_task("  Processing lectures", total=len(lecture_items))
                for item in lecture_items:
                    item_id = item["id"]
                    lecture_name = _sanitize_filename(item["name"])
                    module_id = item.get("moduleId", "")
                    module_info = module_lookup.get(module_id, {})
                    module_slug = module_info.get("slug", f"module-{module_id}")
                    module_index = item.get("_module_index")
                    module_dir = (
                        course_dir / f"{module_index:02d}_{module_slug}"
                        if module_index is not None
                        else course_dir / module_slug
                    )
                    lecture_index = item.get("_lecture_index")
                    lecture_d = _lecture_dir(module_dir, lecture_index, lecture_name)
                    name = f"{lecture_index:02d}_{lecture_name}" if lecture_index is not None else lecture_name

                    try:
                        video_data = self.api.get_lecture_video(course_id, item_id)
                    except Exception as e:  # noqa: BLE001
                        if "transcripts" in enabled:
                            results["transcripts"].append(("❌", name, f"[error]Failed: {e}[/error]"))
                            stats["transcripts"]["failed"] += 1
                        if "videos" in enabled:
                            results["videos"].append(("❌", name, f"[error]Failed: {e}[/error]"))
                            stats["videos"]["failed"] += 1
                        progress.advance(task)
                        continue

                    # Transcript
                    if "transcripts" in enabled:
                        self._write_transcript(video_data, lecture_d, name, results["transcripts"], stats["transcripts"])

                    # Video (queued, downloaded in parallel after this loop)
                    if "videos" in enabled:
                        video_jobs.append((name, video_data, lecture_d))

                    progress.advance(task)

        # ── Video pass (parallel) ────────────────────────────────────
        if "videos" in enabled and video_jobs:
            vd = VideoDownloader(self.api, quality=quality, console=c)
            with Progress(
                SpinnerColumn(style="bright_cyan"),
                TextColumn("[bold]{task.description}[/bold]"),
                BarColumn(bar_width=30, style="dim white", complete_style="bright_cyan", finished_style="bright_green"),
                MofNCompleteColumn(),
                TextColumn("•"),
                TimeElapsedColumn(),
                console=c,
                transient=False,
            ) as progress:
                out = vd.run(video_jobs, progress)
            results["videos"].extend(out["results"])
            self._merge_stats(stats["videos"], out["stats"])

        # ── Asset pass ───────────────────────────────────────────────
        if "assets" in enabled:
            asset_jobs = _build_asset_jobs(materials, module_lookup, course_dir)
            if asset_jobs:
                ad = AssetDownloader(self.api, console=c)
                with Progress(
                    SpinnerColumn(style="bright_cyan"),
                    TextColumn("[bold]{task.description}[/bold]"),
                    BarColumn(bar_width=30, style="dim white", complete_style="bright_cyan", finished_style="bright_green"),
                    MofNCompleteColumn(),
                    TextColumn("•"),
                    TimeElapsedColumn(),
                    console=c,
                    transient=False,
                ) as progress:
                    out = ad.run(asset_jobs, progress)
                results["assets"].extend(out["results"])
                self._merge_stats(stats["assets"], out["stats"])
            else:
                c.print("[warning]  ⚠  No lecture assets (slides/PDFs) found.[/warning]")

        # ── Results + summary ────────────────────────────────────────
        for kind in enabled:
            self._show_results(c, kind, results[kind])
        self._show_summary(c, course_dir, {k: stats[k] for k in enabled})

        any_success = any(stats[k]["success"] for k in enabled)
        return {"success": any_success, "stats": stats}

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _get_subtitle_url(self, video_data: dict) -> str | None:
        videos = video_data.get("linked", {}).get("onDemandVideos.v1", [])
        if not videos:
            return None
        video = videos[0]
        subtitles = video.get("subtitlesTxt" if self.fmt == "txt" else "subtitles", {})
        return subtitles.get(self.language)

    def _write_transcript(self, video_data, lecture_dir, name, results_list, stats_dict) -> None:
        subtitle_url = self._get_subtitle_url(video_data)
        if not subtitle_url:
            results_list.append(("⊘", name, f"[warning]No {self.language} {self.fmt} subtitles[/warning]"))
            stats_dict["skipped"] += 1
            return
        try:
            text = self.api.download_subtitle(subtitle_url)
        except Exception as e:  # noqa: BLE001
            results_list.append(("❌", name, f"[error]Download failed: {e}[/error]"))
            stats_dict["failed"] += 1
            return
        lecture_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{name}.{self.fmt}"
        (lecture_dir / filename).write_text(text, encoding="utf-8")
        results_list.append(("✔", name, f"[muted]{lecture_dir.name}/{filename}[/muted]"))
        stats_dict["success"] += 1

    def _show_overview(self, slug, lecture_items, enabled, quality, course_dir) -> None:
        c = self.console
        info_table = Table.grid(padding=(0, 2))
        info_table.add_column(style="muted", justify="right")
        info_table.add_column(style="bold white")
        info_table.add_row("Course", slug)
        info_table.add_row("Lectures", str(len(lecture_items)))
        info_table.add_row("Transcripts", "On" if "transcripts" in enabled else "Off")
        info_table.add_row("Videos", f"{'On' if 'videos' in enabled else 'Off'}"
                                      + (f" ({quality})" if "videos" in enabled else ""))
        info_table.add_row("Assets", "On" if "assets" in enabled else "Off")
        info_table.add_row("Output", str(course_dir))
        c.print()
        c.print(Panel(info_table, title="[brand]📋  Course Overview[/brand]", border_style="bright_cyan", padding=(1, 2)))
        c.print()

    def _show_results(self, c, kind, results) -> None:
        if not results:
            return
        icon_map = {"✔": "bright_green", "⊘": "yellow", "❌": "red"}
        label = {"transcripts": "📝  Transcripts", "videos": "🎬  Videos", "assets": "📎  Assets"}.get(kind, kind)
        tree = Tree(f"[bold bright_cyan]{label}[/bold bright_cyan]")
        for icon, name, detail in results:
            style = icon_map.get(icon, "white")
            tree.add(f"[{style}]{icon}[/{style}]  [bold]{name}[/bold]  {detail}")
        c.print(tree)
        c.print()

    def _show_summary(self, c, course_dir, stats_by_kind) -> None:
        parts = []
        for kind, st in stats_by_kind.items():
            label = {"transcripts": "Transcripts", "videos": "Videos", "assets": "Assets"}.get(kind, kind)
            bits = []
            if st["success"]:
                bits.append(f"[bright_green]✔ {st['success']} {label}[/bright_green]")
            if st["skipped"]:
                bits.append(f"[yellow]⊘ {st['skipped']} {label}[/yellow]")
            if st["failed"]:
                bits.append(f"[red]✖ {st['failed']} {label}[/red]")
            parts.append("   ".join(bits))
        summary = "\n\n".join(p for p in parts if p)
        summary += f"\n\n[muted]Files saved to [bold]{course_dir}[/bold][/muted]"
        c.print(Panel(summary, title="[brand]✨  Summary[/brand]", border_style="bright_green", padding=(1, 2)))

    @staticmethod
    def _zero_stats() -> dict:
        return {"success": 0, "skipped": 0, "failed": 0, "total": 0}

    @staticmethod
    def _empty_stats(enabled: set[str]) -> dict:
        return {"success": False, "stats": {k: TranscriptDownloader._zero_stats() for k in enabled}}

    @staticmethod
    def _merge_stats(target: dict, source: dict) -> None:
        for key in ("success", "skipped", "failed", "total"):
            target[key] = target.get(key, 0) + source.get(key, 0)
