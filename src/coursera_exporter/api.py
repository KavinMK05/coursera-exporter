import time
import requests
from pathlib import Path
from urllib.parse import urljoin

from rich.console import Console


COURSERA_BASE = "https://www.coursera.org"
COURSERA_VERSION = "e184c443bbe09b70cbcebf2ba22b3b1067d7e119"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0",
    "Accept": "*/*",
    "Accept-Language": "en",
    "X-Coursera-Application": "ondemand",
    "X-Coursera-Version": COURSERA_VERSION,
    "X-Requested-With": "XMLHttpRequest",
}


def _build_headers(cookie: str, referer: str | None = None) -> dict:
    headers = HEADERS.copy()
    headers["Cookie"] = cookie
    if referer:
        headers["Referer"] = referer
    return headers


class CourseAPI:
    def __init__(self, cookie: str, console: Console | None = None):
        self.cookie = cookie
        self.session = requests.Session()
        self.console = console or Console()

    def _get(self, url: str, referer: str | None = None, max_retries: int = 3) -> requests.Response:
        headers = _build_headers(self.cookie, referer)
        last_exception: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                last_exception = e
                if attempt == max_retries - 1:
                    break
                wait = 2 ** attempt
                self.console.print(
                    f"  [warning]⟳  Request failed, retrying in {wait}s…[/warning] [muted]({e})[/muted]"
                )
                time.sleep(wait)
        raise last_exception  # type: ignore[misc]

    def get_course_materials(self, slug: str) -> dict:
        url = (
            f"{COURSERA_BASE}/api/onDemandCourseMaterials.v2/"
            f"?q=slug&slug={slug}"
            f"&includes=modules%2Clessons%2CpassableItemGroups%2CpassableItemGroupChoices%2CpassableLessonElements%2Citems%2Ctracks%2CgradePolicy%2CgradingParameters%2CembeddedContentMapping"
            f"&fields=moduleIds%2ConDemandCourseMaterialModules.v1(name%2Cslug%2Cdescription%2CtimeCommitment%2ClessonIds%2Coptional%2ClearningObjectives)%2ConDemandCourseMaterialLessons.v1(name%2Cslug%2CtimeCommitment%2CelementIds%2Coptional%2CtrackId)%2ConDemandCourseMaterialPassableItemGroups.v1(requiredPassedCount%2CpassableItemGroupChoiceIds%2CtrackId)%2ConDemandCourseMaterialPassableItemGroupChoices.v1(name%2Cdescription%2CitemIds)%2ConDemandCourseMaterialPassableLessonElements.v1(gradingWeight%2CisRequiredForPassing)%2ConDemandCourseMaterialItems.v2(name%2CoriginalName%2Cslug%2CtimeCommitment%2CcontentSummary%2CisLocked%2ClockableByItem%2CitemLockedReasonCode%2CtrackId%2ClockedStatus%2CitemLockSummary%2CcustomDisplayTypenameOverride)%2ConDemandCourseMaterialTracks.v1(passablesCount)%2ConDemandGradingParameters.v1(gradedAssignmentGroups)%2CcontentAtomRelations.v1(embeddedContentSourceCourseId%2CsubContainerId)"
            f"&showLockedItems=true"
        )
        referer = f"{COURSERA_BASE}/learn/{slug}/home/module/1"
        response = self._get(url, referer)
        data = response.json()

        if not data.get("elements"):
            raise ValueError(f"Course '{slug}' not found or no data returned")

        return data

    def get_lecture_video(self, course_id: str, item_id: str) -> dict:
        url = (
            f"{COURSERA_BASE}/api/onDemandLectureVideos.v1/"
            f"{course_id}~{item_id}"
            f"?includes=video"
            f"&fields=onDemandVideos.v1(sources%2Csubtitles%2CsubtitlesTxt%2CsubtitlesAssetTags%2CdubbedSources%2CdubbedSubtitlesVtt%2CaudioDescriptionVideoSources%2ChlsUrl%2CdashUrl)"
            f"%2CdisableSkippingForward%2CstartMs%2CendMs"
        )
        response = self._get(url)
        return response.json()

    def download_subtitle(self, relative_url: str) -> str:
        url = urljoin(COURSERA_BASE, relative_url)
        response = self._get(url)
        return response.text

    def download_file(self, url: str, dest, referer: str | None = None, chunk_size: int = 1024 * 1024) -> int:
        """Stream a binary file (video/asset) to ``dest`` using the authenticated
        session. Returns the number of bytes written. ``dest`` may be a path or a
        file-like object."""
        headers = _build_headers(self.cookie, referer)
        written = 0
        with self.session.get(url, headers=headers, stream=True, timeout=120) as response:
            response.raise_for_status()
            if hasattr(dest, "write"):
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        dest.write(chunk)
                        written += len(chunk)
            else:
                dest = Path(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            written += len(chunk)
        return written


def _coerce_source(entry) -> tuple[str | None, str | None]:
    """Coerce a single ``sources`` entry (which may be a URL string or a dict)
    into ``(url, type)``. Coursera uses either ``src`` or ``url`` for the link."""
    if isinstance(entry, str):
        return entry, ""
    if isinstance(entry, dict):
        src = entry.get("src") or entry.get("url")
        return src, entry.get("type", "") or ""
    return None, None


def get_video_streams(video_data: dict) -> dict:
    """Normalize a ``get_lecture_video`` response into a consistent shape:
    ``{"sources": {res: [{"src","type"}, ...]}, "dash": url|None, "hls": url|None}``.

    Coursera returns ``sources`` in several shapes across courses — a dict of
    resolution→list-of-dicts, a dict of resolution→list-of-URL-strings,
    resolution→single URL string, a flat list, or the newer nested shape with
    ``byResolution`` / ``playlists`` — so we normalize all of them.
    """
    videos = video_data.get("linked", {}).get("onDemandVideos.v1", [])
    if not videos:
        return {"sources": {}, "dash": None, "hls": None}
    video = videos[0]
    sources = video.get("sources")

    normalized: dict[str, list] = {}
    dash = video.get("dashUrl") or video.get("dash")
    hls = video.get("hlsUrl") or video.get("hls")

    if isinstance(sources, dict):
        # Newer nested shape: sources.byResolution[res] = {mp4VideoUrl, webMVideoUrl, ...}
        by_res = sources.get("byResolution")
        if isinstance(by_res, dict):
            for res_key, entry in by_res.items():
                if not isinstance(entry, dict):
                    continue
                res = res_key.rstrip("p") or res_key  # "720p" -> "720"
                mp4 = entry.get("mp4VideoUrl")
                webm = entry.get("webMVideoUrl")
                if mp4:
                    normalized.setdefault(res, []).append({"src": mp4, "type": "video/mp4"})
                if webm:
                    normalized.setdefault(res, []).append({"src": webm, "type": "video/webm"})
            # DASH/HLS manifests live under sources.playlists
            playlists = sources.get("playlists") or {}
            if not dash and playlists.get("mpeg-dash"):
                dash = playlists.get("mpeg-dash")
            if not hls and playlists.get("hls"):
                hls = playlists.get("hls")
        else:
            # Older shape: dict of resolution -> list of {src/url, type}
            for res, entries in sources.items():
                if not isinstance(entries, list):
                    entries = [entries]
                for entry in entries:
                    src, typ = _coerce_source(entry)
                    if src:
                        normalized.setdefault(str(res), []).append({"src": src, "type": typ or ""})
    elif isinstance(sources, list):
        for entry in sources:
            if isinstance(entry, dict):
                res = str(entry.get("res") or entry.get("resolution") or "0")
                src = entry.get("src") or entry.get("url")
                typ = entry.get("type", "") or ""
            else:
                res, src, typ = "0", entry, ""
            if src:
                normalized.setdefault(res, []).append({"src": src, "type": typ or ""})
    elif isinstance(sources, str):
        normalized.setdefault("0", []).append({"src": sources, "type": ""})

    return {
        "sources": normalized,
        "dash": dash,
        "hls": hls,
    }


def pick_source(sources: dict, quality: str) -> tuple[str | None, str | None]:
    """Pick a progressive mp4 URL from ``sources`` for the requested ``quality``
    ("360"/"540"/"720"/"best"). Returns ``(url, resolution_label)`` or
    ``(None, None)`` when only HLS/DASH streams are available."""
    if not sources:
        return None, None

    progressive: dict[int, str] = {}
    for res, entries in sources.items():
        for entry in entries:
            src = entry.get("src") if isinstance(entry, dict) else entry
            if not src:
                continue
            if isinstance(src, str) and (src.endswith(".mp4") or (isinstance(entry, dict) and entry.get("type") == "video/mp4")):
                try:
                    progressive[int(res)] = src
                except (TypeError, ValueError):
                    progressive[0] = src

    if not progressive:
        return None, None

    if quality == "best":
        chosen = max(progressive)
    else:
        try:
            q = int(quality)
        except ValueError:
            q = max(progressive)
        if q in progressive:
            chosen = q
        else:
            lower = [r for r in progressive if r <= q]
            chosen = max(lower) if lower else max(progressive)

    return progressive[chosen], f"{chosen}p"


def parse_asset_items(materials_data: dict) -> list[dict]:
    """Extract downloadable supplement assets (slides/PDFs/etc.) from a course
    materials response. Returns a list of dicts with keys:
    ``item_id, module_id, item_name, asset_name, url``."""
    items = materials_data.get("linked", {}).get("onDemandCourseMaterialItems.v2", [])
    assets: list[dict] = []
    for item in items:
        content_type = item.get("contentSummary", {}).get("typeName", "")
        if content_type not in ("supplementary", "supplement"):
            continue
        definition = item.get("contentSummary", {}).get("definition", {})
        for asset in definition.get("assets", []) or []:
            url = asset.get("url")
            if not url:
                continue
            assets.append({
                "item_id": item.get("id"),
                "module_id": item.get("moduleId", ""),
                "item_name": item.get("name") or "assets",
                "asset_name": asset.get("name") or "asset",
                "url": url,
            })
    return assets
