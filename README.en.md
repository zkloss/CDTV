# CDTV - AI Comic & Short Drama Automation Client

English | [简体中文](README.md)

> **Windows installer (recommended):** [Download the latest release](https://github.com/zkloss/CDTV/releases/latest) · custom install directory · no Python / Node.js / Java required
>
> This repository is the source backup. To skip the development setup, download `CDTV_Setup_*.exe` from Releases.

A local desktop application built with Vue 3, pywebview, Python, and Playwright for automating the end-to-end AI comic-drama and short-video production workflow. It integrates project management, asset organization, audio-visual director storyboard editing, video batch generation, and task scheduling into a unified workspace. **Project data and assets are stored locally; no backend deployment, Java runtime, or client registration/login is required. Image, video, audio, and text generation all use custom model APIs configured in Settings.**

> **This project shares code for noncommercial learning and exchange only. It provides no commercial authorization.**
>
> Users bear the consequences of their use of this project. To the extent permitted by applicable law, the project and its authors accept no liability for losses, disputes, or other consequences arising from such use. Liability that cannot legally be excluded remains unaffected. See [LICENSE](LICENSE) for the permitted scope; verify third-party service and media permissions independently.

---

## ✨ CDTV 2.0 Core Feature Upgrades

- 🎬 **Integrated V7.4.20 Director Engine**:
  - Utilizes a modular matrix of **1 General Director + 12 Specialized Assistant Directors** (scriptwriting, character design, scene art, audio-visual storyboarding, prompt engineering, etc.).
  - Built-in **48 industrial-grade rule sets** covering shot composition, camera movement, emotional dynamics, lighting, and continuity control.
- 📋 **M1 Wirelist Industrial Management**:
  - Rigorous asset-to-shot wirelist mapping guarantees **1:1 shot extraction**, preventing LLMs from skipping, collapsing, or compressing storyboard shots.
- ⚡ **Seedance 2.5 / 2.0 Dual Adaptation**:
  - Seamless prompt encapsulation for custom relays and direct API gateways supporting both Seedance 2.5 and 2.0 generation specs.
  - Implements **D-lock tail-frame anchoring** and multi-camera smooth transitions to significantly enhance character and scene consistency across shots.
- 🧩 **Universal Script Import + AI Restructuring**:
  - Imports Markdown, TXT, Word (docx / doc), PDF, Excel (xlsx / xls), CSV, JSON, whole-season folders, and pasted text, auto-adapting screenplays, novel chapters, and loose shot lists into structured creation data.
  - When a novel or rough text is detected (few shots, no dialogue fields), a text model can restructure it into a production-ready storyboard format with shot numbers, duration, scene, visuals, dialogue, camera language, ambience, transitions, and shooting constraints.
- 🔓 **Clean Open-Source Defaults + Workflow Presets**:
  - The model library starts completely empty on first launch — no preset relays or third-party providers.
  - Model Management ships with one-click workflow presets: AutoDL ComfyUI (27 built-in H3 video workflows), RunningHub, LiblibAI, native ComfyUI (port 8188), and custom endpoints, with remote model list fetching.
- 📺 **Refreshed Brand & UI**:
  - Brand-new TV application icon and visual identity.
  - Isolated local task concurrency with workspace state preservation.

---

## Features

- **Project management**: Project and chapter management, Markdown script editing, real-time saving, and heading anchor navigation.
- **Script document import**: Import .md / .txt / .docx / .doc / .pdf / .xlsx / .xls / .csv / .json files, whole-season folders, or pasted text; novels and rough manuscripts can be restructured by a text model into industrial-grade storyboard scripts.
- **Model management & workflow presets**: Configure text / image / video / audio models, fill in one click from AutoDL ComfyUI, RunningHub, LiblibAI, native ComfyUI, or custom workflow presets, and fetch remote model lists automatically.
- **Asset library**: Categorized management and local preview of prompts, characters / scenes / props / white models / audio assets.
- **Video generation**: Local image selection, prompt tuning, aspect ratio and duration controls, task progress and result sync, generated through model APIs configured in Settings.

---

## Getting Started

1. **Start the client**: on Windows, run `CDTV_Setup_*.exe` from Releases and choose an installation directory; or run `CDTV.exe` from a portable package, or follow the [development guide](docs/DEVELOPMENT.en.md) to run from source.
2. **Create a project**: organize chapters, edit the Markdown script, and add local assets.
3. **Prepare storyboards**: create a video task and edit shots, or import creation-data JSON.
4. **Configure model APIs**: the model library starts empty (clean open-source defaults, no preset relays). Add text / image / video / audio models under Settings → Model Management; entering an API URL can fetch remote model lists, or use the one-click workflow presets.
5. **Generate and review**: attach images, enter descriptions, select parameters, and monitor generation progress.

---

## Local Storage & Boundaries

Project data and uploaded files are stored locally by default:
- **Built-in storage**: `local_storage.py` serves data and files on `127.0.0.1:18081` at startup.
- **Single local user**: No cloud registration or login required.
- Default database: `data/storage/storage.db` (SQLite).

---

## AI Creation Data & JSON Import

The project ships a built-in `SKILL/` directory containing the director engine library and rule documents (`SKILL.md` plus `references/` data models and rule docs) as an industrial standard for transforming scripts into structured, verifiable comic-drama storyboard data.

Creation data can be imported into a project as JSON to validate the import flow and field structure. Script documents (.md, .txt, .docx, .doc, .pdf, .xlsx, .xls, .csv, .json) and folders can also be imported directly and auto-adapted into structured creation data.

---

## Development & Packaging

For running from source, environment requirements, frontend dev mode, and PyInstaller builds, see [docs/DEVELOPMENT.en.md](docs/DEVELOPMENT.en.md).

---

## License

This project uses the [PolyForm Noncommercial License 1.0.0](LICENSE). Noncommercial learning, research, modification, and sharing are permitted within the license terms. Commercial use or distribution is not permitted under this license.
