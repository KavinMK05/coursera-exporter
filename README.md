# 📚 Coursera Exporter

A beautiful CLI tool to bulk-download transcripts, subtitles, lecture videos, and slides from any Coursera course you're enrolled in.

![CLI Preview](https://raw.githubusercontent.com/KavinMK05/coursera-exporter/master/preview.png)

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-brightgreen)
[![GitHub stars](https://img.shields.io/github/stars/KavinMK05/coursera-exporter?style=social)](https://github.com/KavinMK05/coursera-exporter)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/coursera-exporter?period=total&units=NONE&left_color=BLACK&right_color=RED&left_text=downloads)](https://pepy.tech/projects/coursera-exporter)

> 🌐 **Online docs:** https://kavinmk05.github.io/coursera-exporter/

---

## ✨ Features

- **Interactive prompts** — guided step-by-step experience, no need to memorize flags
- **Bulk download** — grabs every lecture transcript in a course at once
- **Organized output** — files are neatly sorted into module folders
- **Progress tracking** — real-time progress bar with download status
- **Retry logic** — automatic retries with exponential backoff on failures
- **Multiple formats** — Markdown (`.md`) by default, with `.txt` (plain text)
  and `.srt` (subtitle) formats available
- **Multi-language** — download transcripts in any available language
- **Video downloads** — grab every lecture `.mp4` in your chosen quality (opt-in)
- **Slides & PDFs** — download attached lecture assets/supplements (opt-in)
- **Reading pages** — extract every reading page (syllabi, overviews, glossaries,
  suggested readings…) as clean **Markdown + HTML**, with embedded file
  attachments (PDFs, ZIPs…) downloaded alongside (on by default)
- **Flexible exports** — pick any combination: transcripts, videos, assets, or
  readings alone, or all together. Transcripts and videos are kept together per
  lecture; assets and readings are saved into their own per-item folders under
  the module.

---

## 📦 Installation

Install from PyPI:

```bash
pip install coursera-exporter
```

Or install from source (for contributors / latest unreleased changes):

```bash
git clone https://github.com/KavinMK05/coursera-exporter.git
cd coursera-exporter

# Install in editable mode
pip install -e .
```

---

## 🚀 Usage

### Quick Start

No flags needed — just run the command and follow the prompts:

```bash
coursera-exporter
```

That's it. The tool walks you through everything interactively, so you never have to memorize flags.

### Interactive Mode (recommended)

Just run the command with no arguments — it will guide you through everything:

```bash
coursera-exporter
```

You'll be prompted for:

1. **CAUTH cookie** — your Coursera authentication token
2. **Course slug** — the identifier from the course URL
3. **Options** — four toggles (transcripts / videos / slides / readings), then
   video quality (when videos on), then language, format, and output directory

### CLI Mode

Prefer to skip the prompts? Pass everything as flags for scripting / automation:

```bash
coursera-exporter \
  --cookie "YOUR_CAUTH_VALUE" \
  --slug "machine-learning" \
  --language en \
  --format srt \
  --output ./transcripts
```

### All Options

| Flag             | Short | Default      | Description                                       |
| ---------------- | ----- | ------------ | ------------------------------------------------- |
| `--cookie`       | `-c`  | _(prompted)_ | CAUTH cookie value                                |
| `--slug`         | `-s`  | _(prompted)_ | Course slug from URL                              |
| `--language`     | `-l`  | `en`         | Subtitle language code                            |
| `--format`       |       | `md`         | Transcript format (`md`, `txt`, or `srt`)         |
| `--output`       | `-o`  | `./output`   | Parent output directory                           |
| `--videos`       |       | `off`        | Download lecture videos                           |
| `--assets`       |       | `off`        | Download lecture assets (slides/PDFs)            |
| `--readings`     |       | `on`         | Extract reading pages (text + attached files)    |
| `--no-transcripts` |     | _(transcripts on)_ | Disable transcripts (export videos/assets alone) |
| `--no-readings`  |       | _(readings on)_ | Disable reading page extraction                |
| `--quality`      |       | `best`       | Video quality: `360`/`540`/`720`/`best`          |

---

## 🔑 Getting Your CAUTH Cookie

1. Open [coursera.org](https://www.coursera.org) and **log in**
2. Open **DevTools** (`F12` or `Ctrl+Shift+I`)
3. Go to **Application** → **Cookies** → `https://www.coursera.org`
4. Find the cookie named **`CAUTH`**
5. Copy its **Value**

> [!IMPORTANT]
> You must be **enrolled** in the course to download its transcripts.

---

## 🎬 Downloading Videos & Assets

Transcripts are downloaded by default. Videos and slides/PDFs are **opt-in** and
can be combined with transcripts — or exported **on their own**:

```bash
# Transcripts + videos (best quality) + slides
coursera-exporter -c "YOUR_CAUTH" -s machine-learning --videos --quality best --assets

# Videos ALONE (skip transcripts)
coursera-exporter -c "YOUR_CAUTH" -s machine-learning --videos --no-transcripts

# Slides/PDFs ALONE
coursera-exporter -c "YOUR_CAUTH" -s machine-learning --assets --no-transcripts
```

> [!IMPORTANT]
> You must be **enrolled** in the course, and the **CAUTH cookie** is required
> for the video CDN — the same cookie you use for transcripts.

> [!NOTE]
> Some courses only serve HLS/DASH streams. For those, install `yt-dlp` (+ `ffmpeg`)
> and it will be used automatically:
> `pip install yt-dlp ffmpeg-downloader`

## 📖 Reading Pages

Every reading page (course overviews, syllabi, glossaries, suggested readings,
supplementary articles…) is extracted as **clean Markdown** plus a styled
**HTML** copy, and any files embedded in the reading (lecture transcript PDFs,
spreadsheets, ZIPs…) are downloaded right next to them:

```bash
# Readings ALONE (skip transcripts)
coursera-exporter -c "YOUR_CAUTH" -s machine-learning --no-transcripts

# Transcripts + videos, without readings
coursera-exporter -c "YOUR_CAUTH" -s machine-learning --no-readings
```

Readings use Coursera's authenticated asset CDN for attachments, so the same
CAUTH cookie is required.

---

## 📁 Output Structure

Transcripts and videos are grouped into per-lecture folders, while slides/PDFs
(assets) and reading pages get their own per-item folders — all under the same
indexed module folder (e.g. `01_introduction-to-ml`):

```
output/
└── machine-learning/
    └── 01_introduction-to-ml/          ← module folder (shared by everything)
        ├── 01_Welcome to Machine Learning/
        │   ├── 01_Welcome to Machine Learning.md   ← transcript (Markdown, default)
        │   └── 01_Welcome to Machine Learning.mp4   ← video (if enabled)
        ├── 02_What is Machine Learning/
        │   ├── 02_What is Machine Learning.md
        │   └── 02_What is Machine Learning.mp4
        ├── Lecture Slides/             ← each supplement item gets its own folder
        │   └── lecture-slides.pdf
        └── 01_Course Overview/         ← each reading page gets its own folder
            ├── 01_Course Overview.md   ← extracted Markdown
            ├── 01_Course Overview.html ← styled HTML copy
            └── Week 1 Transcript.pdf   ← file embedded in the reading
```

(When only some content types are selected, the corresponding folders simply
contain fewer files.)

### Transcript format

Transcripts are Markdown (`.md`) by default — the raw subtitle text is cleaned
up and grouped into readable paragraphs under a heading:

```markdown
# 01_Welcome to Machine Learning

Welcome to Machine Learning. In this course, you will learn about the most
effective machine learning techniques... 

You'll gain the practical skills needed to apply these methods... 
```

Use `--format txt` for the raw plain text exactly as Coursera serves it, or
`--format srt` for timestamped subtitles.

---

## 🔧 Finding the Course Slug

The slug is the part of the URL after `/learn/`:

```
https://www.coursera.org/learn/machine-learning
                                └── this is the slug
```

---

## 📋 Requirements

- Python **3.10+**
- A Coursera account with enrollment in the target course
- _(Optional)_ `yt-dlp` and `ffmpeg` — only needed for courses that serve
  HLS/DASH video streams or require stream merging:
  `pip install yt-dlp ffmpeg-downloader`

---

## 📄 License

MIT
