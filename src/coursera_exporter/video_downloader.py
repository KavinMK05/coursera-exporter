import re
from concurrent.futures import ThreadPoolExecutor, as_completed
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

from .api import CourseAPI, get_video_streams, pick_source


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = name.strip()
    return name[:200]


class VideoDownloader:
    """Downloads lecture videos into per-lecture folders.

    Uses the already-fetched ``video_data`` (no extra API call) and prefers
    progressive mp4 streams. Falls back to ``yt-dlp`` for HLS/DASH-only courses.
    """

    def __init__(
        self,
        api: CourseAPI,
        quality: str = "best",
        max_workers: int = 4,
        console: Console | None = None,
    ):
        self.api = api
        self.quality = quality
        self.max_workers = max_workers
        self.console = console or Console()

    def _download_one(self, name: str, video_data: dict, lecture_dir: Path) -> tuple[str, str, str]:
        try:
            streams = get_video_streams(video_data)
            url, label = pick_source(streams["sources"], self.quality)

            if not url:
                hls = streams.get("hls")
                dash = streams.get("dash")
                any_src = None
                seen_types: set[str] = set()
                # Scan sources for HLS/DASH URLs if the dedicated fields are absent.
                # Coursera groups the combined stream under a non-numeric key such
                # as "audio"; match by both extension and MIME type.
                for entries in streams["sources"].values():
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        src = entry.get("src") or entry.get("url")
                        if not isinstance(src, str):
                            continue
                        typ = (entry.get("type") or "").lower()
                        seen_types.add(typ)
                        if not any_src:
                            any_src = src
                        if ("mpegurl" in typ or src.endswith(".m3u8")) and not hls:
                            hls = src
                        elif ("dash" in typ or src.endswith(".mpd")) and not dash:
                            dash = src
                if dash:
                    return self._download_with_ytdlp(dash, lecture_dir, name, "DASH")
                if hls:
                    return self._download_with_ytdlp(hls, lecture_dir, name, "HLS")
                if any_src:
                    # Unknown stream type (often an HLS/DASH manifest) — let yt-dlp try.
                    return self._download_with_ytdlp(any_src, lecture_dir, name, "STREAM")
                keys = list(streams["sources"].keys())
                detail = "[warning]No downloadable video stream[/warning]"
                if keys:
                    detail += f" [muted](resolutions seen: {keys}; types: {sorted(seen_types)})[/muted]"
                else:
                    detail += " [muted](empty sources)[/muted]"
                return ("⊘", name, detail)

            lecture_dir.mkdir(parents=True, exist_ok=True)
            dest = lecture_dir / f"{name}.mp4"
            if dest.exists():
                return ("⊘", name, f"[yellow]Already exists: {dest.name}[/yellow]")
            self.api.download_file(url, dest, referer=url)
            return ("✔", name, f"[muted]{lecture_dir.name}/{dest.name}[/muted]")
        except Exception as e:  # noqa: BLE001
            return ("❌", name, f"[error]{e}[/error]")

    def _download_with_ytdlp(self, url: str, lecture_dir: Path, name: str, kind: str) -> tuple[str, str, str]:
        try:
            import yt_dlp  # lazy import — optional dependency
        except ImportError:
            return (
                "❌",
                name,
                f"[error]yt-dlp required for {kind} streams. Install: pip install yt-dlp ffmpeg-downloader[/error]",
            )
        lecture_dir.mkdir(parents=True, exist_ok=True)
        ydl_opts = {
            "outtmpl": str(lecture_dir / f"{name}.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            return ("✔", name, f"[muted]{lecture_dir.name}/{name}.mp4[/muted]")
        except Exception as e:  # noqa: BLE001
            return ("❌", name, f"[error]yt-dlp failed: {e}[/error]")

    def run(self, jobs: list[tuple[str, dict, Path]], progress: Progress | None = None) -> dict:
        """``jobs`` is a list of ``(lecture_name, video_data, lecture_dir)``.

        Returns a stats dict ``{"success", "skipped", "failed", "total"}``."""
        stats = {"success": 0, "skipped": 0, "failed": 0, "total": len(jobs)}
        results: list[tuple[str, str, str]] = []

        def _worker(job):
            return self._download_one(*job)

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = [pool.submit(_worker, job) for job in jobs]
            task = None
            if progress is not None:
                task = progress.add_task("  Downloading videos", total=stats["total"])
            for future in as_completed(futures):
                icon, name, detail = future.result()
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


class AssetDownloader:
    """Downloads supplement assets (slides/PDFs) into per-item folders."""

    def __init__(self, api: CourseAPI, console: Console | None = None):
        self.api = api
        self.console = console or Console()

    def run(self, jobs: list[tuple[str, str, Path]], progress: Progress | None = None) -> dict:
        """``jobs`` is a list of ``(item_name, url, asset_dir)``.

        Returns a stats dict."""
        stats = {"success": 0, "skipped": 0, "failed": 0, "total": len(jobs)}
        results: list[tuple[str, str, str]] = []

        task = None
        if progress is not None:
            task = progress.add_task("  Downloading assets", total=stats["total"])

        for item_name, url, asset_dir in jobs:
            asset_name = _sanitize_filename(Path(url.split("?")[0]).name)
            try:
                asset_dir.mkdir(parents=True, exist_ok=True)
                dest = asset_dir / asset_name
                if dest.exists():
                    stats["skipped"] += 1
                    results.append(("⊘", item_name, f"[yellow]Already exists: {asset_name}[/yellow]"))
                else:
                    self.api.download_file(url, dest, referer=url)
                    stats["success"] += 1
                    results.append(("✔", item_name, f"[muted]{asset_dir.name}/{asset_name}[/muted]"))
            except Exception as e:  # noqa: BLE001
                stats["failed"] += 1
                results.append(("❌", item_name, f"[error]{e}[/error]"))
            if task is not None:
                progress.advance(task)

        return {"stats": stats, "results": results}
