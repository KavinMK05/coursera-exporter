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
- **Multiple formats** — supports both `.txt` (plain text) and `.srt` (subtitle) formats
- **Multi-language** — download transcripts in any available language
- **Video downloads** — grab every lecture `.mp4` in your chosen quality (opt-in)
- **Slides & PDFs** — download attached lecture assets/supplements (opt-in)
- **Flexible exports** — pick any combination: transcripts, videos, or assets
  alone, or all together. Transcripts and videos are kept together per lecture;
  assets are saved into their own per-item folders under the module.

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
3. **Options** — three toggles (transcripts / videos / slides), then video
   quality (when videos on), then language, format, and output directory

### CLI Mode

Prefer to skip the prompts? Pass everything as flags for scripting / automation:

```bash
coursera-exporter \
  --cookie "YOUR_CAUTH_VALUE" \
  --slug "machine-learning" \
  --language en \
  --format txt \
  --output ./transcripts
```

### All Options

| Flag             | Short | Default      | Description                                       |
| ---------------- | ----- | ------------ | ------------------------------------------------- |
| `--cookie`       | `-c`  | _(prompted)_ | CAUTH cookie value                                |
| `--slug`         | `-s`  | _(prompted)_ | Course slug from URL                              |
| `--language`     | `-l`  | `en`         | Subtitle language code                            |
| `--format`       |       | `txt`        | Output format (`txt` or `srt`)                    |
| `--output`       | `-o`  | `./output`   | Parent output directory                           |
| `--videos`       |       | `off`        | Download lecture videos                           |
| `--assets`       |       | `off`        | Download lecture assets (slides/PDFs)            |
| `--no-transcripts` |     | _(transcripts on)_ | Disable transcripts (export videos/assets alone) |
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

---

## 📁 Output Structure

Transcripts and videos are grouped into per-lecture folders, and slides/PDFs
(assets) into their own per-item folder — all under the same indexed module
folder (e.g. `01_introduction-to-ml`):

```
output/
└── machine-learning/
    └── 01_introduction-to-ml/          ← module folder (shared by lectures + assets)
        ├── 01_Welcome to Machine Learning/
        │   ├── 01_Welcome to Machine Learning.txt   ← transcript
        │   └── 01_Welcome to Machine Learning.mp4   ← video (if enabled)
        ├── 02_What is Machine Learning/
        │   ├── 02_What is Machine Learning.txt
        │   └── 02_What is Machine Learning.mp4
        ├── Lecture Slides/             ← each supplement item gets its own folder
        │   └── lecture-slides.pdf
        └── Reading Notes/
            └── notes.pdf
```

(When only one content type is selected, the corresponding folders simply
contain fewer files.)

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
