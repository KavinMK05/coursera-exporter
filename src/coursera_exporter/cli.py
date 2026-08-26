import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text
from rich.theme import Theme

from .api import CourseAPI
from .downloader import TranscriptDownloader
from . import __version__

# ── Custom theme ──────────────────────────────────────────────────────
custom_theme = Theme({
    "brand":    "bold bright_cyan",
    "accent":   "bright_magenta",
    "success":  "bold bright_green",
    "warning":  "bold yellow",
    "error":    "bold red",
    "muted":    "dim white",
    "info":     "bright_blue",
})

console = Console(theme=custom_theme)

GITHUB_URL = "https://github.com/KavinMK05/coursera-exporter"
GITHUB_SPONSORS_URL = "https://github.com/sponsors/KavinMK05?frequency=recurring"

BANNER = r"""[bright_cyan]
   ██████╗ ██████╗ ██╗   ██╗██████╗ ███████╗███████╗██████╗  █████╗
  ██╔════╝██╔═══██╗██║   ██║██╔══██╗██╔════╝██╔════╝██╔══██╗██╔══██╗
  ██║     ██║   ██║██║   ██║██████╔╝███████╗█████╗  ██████╔╝███████║
  ██║     ██║   ██║██║   ██║██╔══██╗╚════██║██╔══╝  ██╔══██╗██╔══██║
  ╚██████╗╚██████╔╝╚██████╔╝██║  ██║███████║███████╗██║  ██║██║  ██║
   ╚═════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝
[/bright_cyan]"""


def _show_banner() -> None:
    console.print(BANNER)
    subtitle = Text("Coursera Exporter", style="bold bright_magenta")
    subtitle.append("  •  ", style="dim")
    subtitle.append(f"v{__version__}", style="dim bright_cyan")
    console.print(subtitle, justify="center")
    console.print()


def _show_star_message() -> None:
    message = (
        "[bold bright_magenta]⭐  Enjoying Coursera Exporter?[/bold bright_magenta]\n"
        "[muted]If this tool saved you time, please star it on GitHub — it really helps!\n[/muted]"
        f"[link={GITHUB_URL}][bright_cyan]{GITHUB_URL}[/bright_cyan][/link]\n\n"
        "[bold bright_magenta]💛  Love it? Consider supporting the project.[/bold bright_magenta]\n"
        "[muted]Your sponsorship keeps the tool maintained and free for everyone.\n[/muted]"
        f"[link={GITHUB_SPONSORS_URL}][bright_cyan]{GITHUB_SPONSORS_URL}[/bright_cyan][/link]"
    )
    console.print()
    console.print(
        Panel(
            message,
            title="[brand]💛  Support the project[/brand]",
            border_style="bright_cyan",
            padding=(1, 2),
        )
    )


def _normalize_cookie(raw: str) -> str:
    """Accept a raw CAUTH token, CAUTH=value, or a full Cookie header string."""
    raw = raw.strip()
    if "CAUTH=" in raw:
        # Already contains the CAUTH key — treat as a full cookie string
        return raw
    # Bare token value — wrap it
    return f"CAUTH={raw}"


def _prompt_cookie() -> str:
    console.print(
        Panel(
            "[muted]Paste your [bold bright_cyan]Cookie[/bold bright_cyan] header or just the [bold bright_cyan]CAUTH[/bold bright_cyan] value.\n"
            "You can copy the full Cookie header from DevTools → Network → any request → Headers.[/muted]",
            title="[brand]🔑  Authentication[/brand]",
            border_style="bright_cyan",
            padding=(1, 2),
        )
    )
    cookie = Prompt.ask("[bright_cyan]  ›[/bright_cyan] [bold]Cookie / CAUTH[/bold]")
    if not cookie.strip():
        console.print("[error]  ✖  Cookie cannot be empty.[/error]")
        raise SystemExit(1)
    return _normalize_cookie(cookie)


def _prompt_slug() -> str:
    console.print()
    console.print(
        Panel(
            "[muted]Enter the course slug from the URL.\n"
            "Example: [bold bright_cyan]coursera.org/learn/[underline]unreal-engine-fundamentals[/underline][/bold bright_cyan][/muted]",
            title="[brand]📚  Course[/brand]",
            border_style="bright_cyan",
            padding=(1, 2),
        )
    )
    slug = Prompt.ask("[bright_cyan]  ›[/bright_cyan] [bold]Course slug[/bold]")
    if not slug.strip():
        console.print("[error]  ✖  Slug cannot be empty.[/error]")
        raise SystemExit(1)
    return slug.strip()


def _prompt_toggle(question: str, default_yes: bool) -> bool:
    default = "y" if default_yes else "n"
    answer = Prompt.ask(
        f"[bright_cyan]  ›[/bright_cyan] [bold]{question}[/bold] [muted](y/n)[/muted]",
        choices=["y", "n"],
        default=default,
    )
    return answer == "y"


def _prompt_options() -> dict:
    console.print()
    console.print(
        Panel(
            "[muted]Choose what to export. You can pick any combination — including "
            "videos or assets on their own.[/muted]",
            title="[brand]⚙  Options[/brand]",
            border_style="bright_cyan",
            padding=(1, 2),
        )
    )
    transcripts = _prompt_toggle("Download transcripts?", default_yes=True)
    videos = _prompt_toggle("Download videos?", default_yes=False)
    assets = _prompt_toggle("Download slides/PDFs (assets)?", default_yes=False)

    quality = "best"
    if videos:
        quality = Prompt.ask(
            "[bright_cyan]  ›[/bright_cyan] [bold]Video quality[/bold] "
            "[muted](360/540/720/best)[/muted]",
            choices=["360", "540", "720", "best"],
            default="best",
        )

    language = "en"
    fmt = "txt"
    if transcripts:
        language = Prompt.ask(
            "[bright_cyan]  ›[/bright_cyan] [bold]Language[/bold]", default="en"
        )
        fmt = Prompt.ask(
            "[bright_cyan]  ›[/bright_cyan] [bold]Format for Transcripts[/bold] [muted](srt/txt)[/muted]",
            choices=["srt", "txt"],
            default="txt",
        )

    output = Prompt.ask(
        "[bright_cyan]  ›[/bright_cyan] [bold]Output directory[/bold]",
        default="./output",
    )
    return {
        "transcripts": transcripts,
        "videos": videos,
        "assets": assets,
        "quality": quality,
        "language": language,
        "fmt": fmt,
        "output_dir": Path(output).resolve(),
    }


def _build_enabled(transcripts: bool, videos: bool, assets: bool) -> set[str]:
    enabled = set()
    if transcripts:
        enabled.add("transcripts")
    if videos:
        enabled.add("videos")
    if assets:
        enabled.add("assets")
    return enabled


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download transcripts, videos, and assets from a Coursera course",
    )
    parser.add_argument(
        "--cookie", "-c",
        help="Coursera authentication cookie (CAUTH value). If omitted, you will be prompted.",
    )
    parser.add_argument(
        "--slug", "-s",
        help="Course slug (e.g. 'unreal-engine-fundamentals'). If omitted, you will be prompted.",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Parent output directory (default: ./output).",
    )
    parser.add_argument(
        "--language", "-l",
        default=None,
        help="Subtitle language code (default: en)",
    )
    parser.add_argument(
        "--format",
        choices=["srt", "txt"],
        default=None,
        help="Subtitle format (default: txt)",
    )
    parser.add_argument(
        "--videos",
        action="store_true",
        help="Download lecture videos.",
    )
    parser.add_argument(
        "--assets",
        action="store_true",
        help="Download lecture assets (slides/PDFs).",
    )
    parser.add_argument(
        "--no-transcripts",
        action="store_true",
        help="Disable transcripts (export videos/assets alone).",
    )
    parser.add_argument(
        "--quality",
        choices=["360", "540", "720", "best"],
        default="best",
        help="Video quality when --videos is set (default: best).",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # ── Interactive mode when cookie/slug not provided ────────────────
    interactive = args.cookie is None or args.slug is None

    if interactive:
        _show_banner()

    # Cookie
    if args.cookie:
        cookie = _normalize_cookie(args.cookie)
    else:
        cookie = _prompt_cookie()

    # Slug
    slug = args.slug if args.slug else _prompt_slug()

    # Options
    if interactive and (
        args.language is None
        and args.format is None
        and args.output is None
        and not args.videos
        and not args.assets
        and not args.no_transcripts
        and args.quality == "best"
    ):
        opts = _prompt_options()
    else:
        transcripts = not args.no_transcripts
        opts = {
            "transcripts": transcripts,
            "videos": args.videos,
            "assets": args.assets,
            "quality": args.quality,
            "language": args.language or "en",
            "fmt": args.format or "txt",
            "output_dir": Path(args.output or "./output").resolve(),
        }

    enabled = _build_enabled(opts["transcripts"], opts["videos"], opts["assets"])
    if not enabled:
        console.print("[error]  ✖  Select at least one content type "
                      "(transcripts, videos, or assets).[/error]")
        raise SystemExit(1)

    console.print()

    # ── Run ───────────────────────────────────────────────────────────
    api = CourseAPI(cookie, console)
    downloader = TranscriptDownloader(
        api=api,
        output_dir=opts["output_dir"],
        language=opts["language"],
        fmt=opts["fmt"],
        console=console,
    )

    try:
        stats = downloader.export(slug, enabled, quality=opts["quality"])
    except ValueError as e:
        console.print(f"\n[error]  ✖  {e}[/error]")
        raise SystemExit(1)
    except KeyboardInterrupt:
        console.print("\n[warning]  ⚠  Interrupted by user.[/warning]")
        raise SystemExit(130)
    except Exception as e:
        console.print(f"\n[error]  ✖  Unexpected error: {e}[/error]")
        raise SystemExit(1)
    else:
        # Only nudge for a star when the export actually downloaded something.
        if stats.get("success"):
            _show_star_message()


if __name__ == "__main__":
    main()
