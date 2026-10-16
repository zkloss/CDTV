# CDTV - AI Comic & Short Drama Automation Client

English | [简体中文](README.md)

A local desktop application built with Vue 3, pywebview, Python, and Playwright for automating the end-to-end AI comic-drama and short-video production workflow. It integrates project management, asset organization, audio-visual director storyboard editing, video batch generation, and multi-account scheduling into a unified workspace. **Project data and assets are stored locally; no backend deployment, Java runtime, or client registration/login is required. Browser video generation requires logging into your respective account.**

> **This project shares code for noncommercial learning and exchange only. It provides no commercial authorization.**
>
> Users bear the consequences of their use of this project. To the extent permitted by applicable law, the project and its authors accept no liability for losses, disputes, or other consequences arising from such use. Liability that cannot legally be excluded remains unaffected. See [LICENSE](LICENSE) for the permitted scope; verify third-party service and media permissions independently.

---

## 📌 Project Origin & Acknowledgements

This project is deeply secondary-developed and upgraded based on the following outstanding open-source projects. Sincere gratitude to the original authors:

1. **Client Desktop Base**: [xulinglin/comoc-drama-client](https://github.com/xulinglin/comoc-drama-client)
   - Thanks to the author for the solid Vue 3 + Python desktop architecture, multi-account browser automation, and storyboard workspace foundation.
2. **Director Engine & Workflow**: [lixiaoxiao9888-create/manju-laoli-skill](https://github.com/lixiaoxiao9888-create/manju-laoli-skill)
   - Thanks to "Manju Old Li" for the industrial-grade AIGC comic-drama Skill suite, powering CDTV 2.0 with the V7.4.20 multi-skill director engine (1 general director + 12 specialized assistant directors), 48 production rule sets, M1 Wirelist management, and Seedance 2.5/2.0 prompt specifications.

---

## ✨ CDTV 2.0 Core Feature Upgrades

- 🎬 **Integrated "Old Li" V7.4.20 Director Engine**:
  - Utilizes a modular matrix of **1 General Director + 12 Specialized Assistant Directors** (scriptwriting, character design, scene art, audio-visual storyboarding, prompt engineering, etc.).
  - Built-in **48 industrial-grade rule sets** covering shot composition, camera movement, emotional dynamics, lighting, and continuity control.
- 📋 **M1 Wirelist Industrial Management**:
  - Rigorous asset-to-shot wirelist mapping guarantees **1:1 shot extraction**, preventing LLMs from skipping, collapsing, or compressing storyboard shots.
- ⚡ **Seedance 2.5 / 2.0 Dual Adaptation**:
  - Seamless prompt encapsulation for custom relays and direct API gateways supporting both Seedance 2.5 and 2.0 generation specs.
  - Implements **D-lock tail-frame anchoring** and multi-camera smooth transitions to significantly enhance character and scene consistency across shots.
- 📺 **Refreshed Brand & UI**:
  - Brand-new TV application icon and visual identity.
  - Multi-account isolated profiles with automated concurrency locking and schedule protection.

---

## Features

- **Project management**: Project and chapter management, Markdown script editing, real-time saving, and heading anchor navigation.
- **Asset library**: Categorized management and local preview of prompts, characters / scenes / props / white models / audio assets.
- **Video generation**: Local image selection, prompt tuning, aspect ratio and duration controls, task progress and result sync.
- **Multi-account management**: Each account has an independent browser profile and login state; the account list is stored locally.
- **Quota & scheduling**: Daily quota tracking for legitimately held accounts, in-use locking, and automatic release on completion to prevent duplicate submissions.
- **Link conversion & video processing**: Retains video downloading, share-link conversion, and watermark processing tools.

---

## Getting Started

1. **Start the client**: run `CDTV.exe` from a release package, or follow the [development guide](docs/DEVELOPMENT.en.md) to run from source.
2. **Create a project**: organize chapters, edit the Markdown script, and add local assets.
3. **Prepare storyboards**: create a video task and edit shots, or import creation-data JSON.
4. **Set up accounts**: add accounts under settings and log in via the automated browser instance.
5. **Generate and review**: attach images, enter descriptions, select parameters, and monitor generation progress.

---

## Local Storage & Boundaries

Project data and uploaded files are stored locally by default:
- **Built-in storage**: `local_storage.py` serves data and files on `127.0.0.1:18081` at startup.
- **Single local user**: No cloud registration or login required.
- Default database: `data/storage/storage.db` (SQLite).

---

## AI Creation Data & Importing Third-Party JSON

The project ships a built-in `SKILL/` directory integrating the industrial specifications from [Manju Old Li AIGC Full-Pipeline Skill (manju-laoli-skill)](https://github.com/lixiaoxiao9888-create/manju-laoli-skill) (`SKILL.md` plus `references/` data models and rule documents) as an industrial standard for transforming scripts into structured, verifiable comic-drama storyboard data.

---

## Development & Packaging

For running from source, environment requirements, frontend dev mode, and PyInstaller builds, see [docs/DEVELOPMENT.en.md](docs/DEVELOPMENT.en.md).

---

## License

This project uses the [PolyForm Noncommercial License 1.0.0](LICENSE). Noncommercial learning, research, modification, and sharing are permitted within the license terms. Commercial use or distribution is not permitted under this license.
