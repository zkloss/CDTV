#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
slice_context.py · 动态原文切片器（Phase Context Slicer · 非手写摘要！）
设计动机：
  全包 140 份 Markdown 合计 2.46MB。若一次性塞进上下文，大模型必然发生「中间注意力坍塌（Lost in the Middle）」。
  而此前删除「运行态微核 agent-system-core.md」是因为手写摘要不随原文同步。
  本脚本直接从**权威原文**按「当前阶段 P0~P5 + 赛道 1~4 + 打戏档 R1~R3 + 模型版本 2.5/2.0/h3 + 素材形态 M0~M2」
  动态提取本阶段必读文件清单、预生成顶部【外挂激活回执头】，并截取各权威文件的核心规则头与模板段。
用法：
  python3 scripts/slice_context.py --stage P3 --track 1 --combat R1 --model 2.5 --mode M1
  python3 scripts/slice_context.py --self-test
"""
import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
SUITE_DIR = os.path.dirname(BASE_DIR)

STAGE_FILES = {
    "P0": [
        "short-drama-director/references/track-routing.md",
        "short-drama-director/references/asset-first-pipeline.md",
        "short-drama-director/references/asset-delivery-modes.md",
        "short-drama-director/references/aspect-ratio-adaptation.md",
        "sd-decision-engine/SKILL.md",
        "sd-decision-engine/references/context-mapping.md",
        "sd-decision-engine/references/emotion-anchor-table.md",
        "sd-decision-engine/references/forbidden-zone-whitelist.md",
    ],
    "P1": [
        "sd-script-engine/SKILL.md",
        "sd-script-engine/references/six-stage-pipeline.md",
        "sd-script-engine/references/dialogue-naturalization.md",
        "short-drama-director/references/dialogue-doctor-7d.md",
        "sd-script-engine/references/story-bible-and-ip.md",
        "sd-script-engine/references/episode-planning.md",
    ],
    "P2": [
        "sd-asset-engine/SKILL.md",
        "sd-asset-engine/references/three-list-extraction.md",
        "sd-asset-engine/references/scene-grid-template.md",
        "sd-asset-engine/references/character-portrait-templates.md",
        "sd-asset-engine/references/prop-template.md",
        "short-drama-director/references/asset-spatial-ledger.md",
        "short-drama-director/references/asset-delivery-modes.md",
    ],
    "P3": [
        "short-drama-director/references/acting-direction.md",
        "short-drama-director/references/blocking-direction.md",
        "sd-storyboard-engine/SKILL.md",
        "sd-storyboard-engine/references/short-drama-camera-system.md",
        "sd-storyboard-engine/references/shot-economy-and-acting.md",
        "sd-storyboard-engine/references/storyboard-sheet-template.md",
        "sd-storyboard-engine/references/plot-deduction-grid.md",
    ],
    "P4": [
        "sd-feed-engine/SKILL.md",
        "sd-feed-engine/references/feed-mode-and-gates.md",
        "sd-feed-engine/references/asset-mapping-and-rules.md",
        "short-drama-director/references/model-adapters.md",
        "short-drama-director/references/segment-splicing.md",
        "short-drama-director/references/prompt-feeding-checklist.md",
    ],
    "P5": [
        "sd-qc-engine/SKILL.md",
        "sd-qc-engine/references/machine-check-manual.md",
        "sd-qc-engine/references/continuity-ledger.md",
        "short-drama-director/references/quality-gate-review.md",
        "short-drama-director/references/storyboard-board-lite.md",
    ],
}

COMBAT_FILES = {
    "R1": [
        "sd-real-engine/SKILL.md",
        "sd-real-engine/references/r1-combat-core.md",
        "sd-real-engine/references/kinetic-chain-11.md",
        "sd-real-engine/references/defense-evasion-rules.md",
        "sd-real-engine/references/impact-physics.md",
        "sd-real-engine/references/camera-action-specs.md",
        "sd-real-engine/references/render-adapters.md",
    ],
    "R2": [
        "sd-combat-engine/SKILL.md",
        "sd-combat-engine/references/combat-iron-laws.md",
        "sd-combat-engine/references/combat-construction.md",
        "sd-combat-engine/references/eight-sentence-masters.md",
        "sd-combat-engine/references/combat-intensity-guardrails.md",
        "sd-combat-engine/references/combat-rhythm-and-load-guardrails.md",
        "sd-combat-engine/references/tier-and-finisher-system.md",
    ],
    "R3": [
        "sd-xuanhuan-engine/SKILL.md",
        "sd-xuanhuan-engine/references/core-combat-laws.md",
        "sd-xuanhuan-engine/references/xuanhuan-elements-vfx.md",
        "sd-xuanhuan-engine/references/grand-scale-domains.md",
        "sd-xuanhuan-engine/references/camera-specs-15modes.md",
        "sd-combat-engine/references/combat-intensity-guardrails.md",
        "sd-combat-engine/references/combat-rhythm-and-load-guardrails.md",
    ],
}


def resolve_files(stage, track="1", combat="none", model="2.5", source="1"):
    files = list(STAGE_FILES.get(stage.upper(), STAGE_FILES["P3"]))
    if source in ("3", "4") and stage.upper() in ("P0", "P1"):
        files.extend([
            "sd-recon-engine/SKILL.md",
            "sd-recon-engine/references/source-ladder.md",
            "sd-recon-engine/references/recon-evidence.md",
            "sd-recon-engine/references/intel-card.md",
        ])
    if track == "2" and stage.upper() in ("P0", "P1", "P4"):
        files.extend([
            "sd-overseas-engine/SKILL.md",
            "sd-overseas-engine/references/language-contract.md",
            "sd-overseas-engine/references/north-american-english.md",
        ])
    elif track == "3" and stage.upper() in ("P0", "P1", "P3", "P4", "P5"):
        files.extend([
            "sd-jieshuo-engine/SKILL.md",
            "sd-jieshuo-engine/references/narration-vo-script.md",
            "sd-jieshuo-engine/references/history-visual-style.md",
            "sd-jieshuo-engine/references/explainer-formulas.md",
        ])
    if stage.upper() in ("P3", "P4") and combat.upper() in COMBAT_FILES:
        files.extend(COMBAT_FILES[combat.upper()])
    if model.lower() == "h3" and stage.upper() in ("P4", "P5"):
        files.append("short-drama-director/references/h3-adapter.md")
    # 去重保序
    seen = set()
    out = []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def build_slice(stage, track="1", combat="none", model="2.5", mode="M1", max_lines_per_file=45):
    files = resolve_files(stage, track, combat, model)
    plugins = sorted({f.split("/")[0] for f in files if f.startswith("sd-")})
    ref_names = [os.path.basename(f) for f in files if "/references/" in f]
    lines = [
        f"# 漫剧老李 V7.4.20 · {stage.upper()} 阶段动态原文切片包（100% 实时取自权威原文）",
        "",
        "## ★ 预生成【外挂激活回执头】（请直接粘贴至本阶段产出物最顶部）",
        "```markdown",
        f"> 素材形态：{mode}",
        f"> 激活外挂：{' + '.join(plugins) if plugins else 'short-drama-director（总控）'}",
        f"> 已读子库：{' / '.join(ref_names[:8])}",
        "> 本段调用外挂指纹：【请在此填入本段实际选用的具体条目：如 E01~E15 编号 / 11环动力链动词 / 尺度四件套 / Voice声线锁】",
        "```",
        "",
        f"## ★ 本阶段必读权威文件清单（共 {len(files)} 份）",
    ]
    for idx, rel in enumerate(files, 1):
        full_p = os.path.join(SUITE_DIR, rel)
        exists = os.path.isfile(full_p)
        sz = os.path.getsize(full_p) if exists else 0
        lines.append(f"{idx}. `{rel}` ({sz // 1024}KB) {'✅' if exists else '❌缺失'}")
    lines.append("")
    lines.append("## ★ 权威原文核心段落实时切片")
    for rel in files:
        full_p = os.path.join(SUITE_DIR, rel)
        if not os.path.isfile(full_p):
            continue
        raw_lines = open(full_p, encoding="utf-8").read().splitlines()
        # 提取前 max_lines_per_file 行 + 所有二级/三级标题行，保持原文零篡改
        head_chunk = raw_lines[:max_lines_per_file]
        headings = [l for l in raw_lines[max_lines_per_file:] if l.startswith(("## ", "### "))]
        lines.append(f"\n### 📄 `{rel}`（原文前 {min(len(raw_lines), max_lines_per_file)} 行 + 章节骨架）")
        lines.extend(head_chunk)
        if headings:
            lines.append("\n> **[后续章节索引 · 按需精读原文]**：" + " ｜ ".join(h.lstrip("# ").strip() for h in headings[:12]))
    return "\n".join(lines)


def self_test():
    for stg in ("P0", "P1", "P2", "P3", "P4", "P5"):
        out = build_slice(stg, track="1", combat="R1" if stg == "P3" else "none", max_lines_per_file=10)
        assert "预生成【外挂激活回执头】" in out and "❌缺失" not in out, f"{stg} slice failed"
    print("[+] slice_context self-test PASSED")
    return 0


def main():
    ap = argparse.ArgumentParser(description="漫剧老李 V7.4.20 动态原文切片器")
    ap.add_argument("--stage", default="P3", choices=["P0", "P1", "P2", "P3", "P4", "P5", "p0", "p1", "p2", "p3", "p4", "p5"])
    ap.add_argument("--track", default="1", choices=["1", "2", "3", "4"])
    ap.add_argument("--combat", default="none", choices=["none", "R1", "R2", "R3", "r1", "r2", "r3"])
    ap.add_argument("--model", default="2.5", choices=["2.5", "2.0", "h3"])
    ap.add_argument("--mode", default="M1", choices=["M0", "M1", "M2"])
    ap.add_argument("--lines", type=int, default=40, help="每份权威文件截取的头部行数")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())
    print(build_slice(args.stage, args.track, args.combat, args.model, args.mode, args.lines))


if __name__ == "__main__":
    main()
