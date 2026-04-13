#!/usr/bin/env python3
"""对比旧 skill 与新候选规则，输出合并建议。

使用示例：
    python merge_candidate.py old-skill.md candidate.json --template ../assets/merge_template.md -o merge.md
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
NEGATIVE_MARKERS = ("不要", "禁止", "不能", "别", "避免")
TAG_KEYWORDS = {
    "structure": ("结构", "顺序", "编号", "四段", "章节"),
    "tone": ("文风", "语气", "简洁", "专业", "口语", "直接"),
    "risk": ("风险", "回归", "异常", "依赖", "事务"),
    "evidence": ("来源", "证据", "依据", "假设"),
    "scope": ("范围", "排除", "只看", "不看", "in scope", "out of scope"),
    "testing": ("测试", "验收"),
    "commit": ("提交信息", "Conventional", "scope"),
    "format": ("格式", "模板", "表格", "输出"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_skill", help="旧 skill Markdown 路径")
    parser.add_argument("candidate", help="候选 skill JSON 路径")
    parser.add_argument("--template", required=True, help="merge_template.md 路径")
    parser.add_argument("-o", "--output", help="输出路径")
    return parser.parse_args()


def load_json(path: str) -> Dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalize(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def similarity(left: str, right: str) -> float:
    left_norm = normalize(left)
    right_norm = normalize(right)
    if len(left_norm) < 2 or len(right_norm) < 2:
        return 0.0
    left_bigrams = {left_norm[index : index + 2] for index in range(len(left_norm) - 1)}
    right_bigrams = {right_norm[index : index + 2] for index in range(len(right_norm) - 1)}
    return len(left_bigrams & right_bigrams) / len(left_bigrams | right_bigrams)


def parse_sections(markdown: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    matches = list(SECTION_RE.finditer(markdown))
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections[title] = markdown[start:end].strip()
    return sections


def extract_bullets(text: str) -> List[str]:
    items = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("- "):
            items.append(line[2:].strip())
        elif re.match(r"^\d+\.\s+", line):
            items.append(re.sub(r"^\d+\.\s+", "", line))
    return items


def extract_old_rules(old_skill_path: str) -> Tuple[str, List[str], List[str]]:
    markdown = Path(old_skill_path).read_text(encoding="utf-8")
    title = "旧 skill"
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    sections = parse_sections(markdown)
    general_rules = extract_bullets(sections.get("通用层规则（所有同类任务通用）", ""))
    personal_rules = []
    for line in sections.get("个人层规则（你的专属工作习惯）", "").splitlines():
        clean = line.strip().lstrip("- ").strip()
        if "：" in clean:
            _, value = clean.split("：", 1)
            for item in re.split(r"[；;]", value):
                item = item.strip()
                if item and item != "未明确提取":
                    personal_rules.append(item)
    return title, general_rules, personal_rules


def classify(text: str) -> str:
    for tag, keywords in TAG_KEYWORDS.items():
        if any(keyword.lower() in text.lower() for keyword in keywords):
            return tag
    return "general"


def find_match(rule: str, candidates: Iterable[str], threshold: float = 0.6) -> str:
    best_item = ""
    best_score = 0.0
    for item in candidates:
        score = similarity(rule, item)
        if score > best_score:
            best_score = score
            best_item = item
    return best_item if best_score >= threshold else ""


def is_conflict(left: str, right: str) -> bool:
    if classify(left) != classify(right):
        return False
    if similarity(left, right) >= 0.6:
        return False
    left_negative = any(marker in left for marker in NEGATIVE_MARKERS)
    right_negative = any(marker in right for marker in NEGATIVE_MARKERS)
    return left_negative != right_negative or True


def format_bullets(items: List[str], fallback: str) -> str:
    if not items:
        return f"- {fallback}"
    return "\n".join(f"- {item}" for item in items)


def build_report(old_title: str, old_general: List[str], old_personal: List[str], candidate: Dict[str, object]) -> Dict[str, str]:
    candidate_general = candidate.get("general_rules", [])
    candidate_personal = candidate.get("personal_rules", [])

    added: List[str] = []
    personal_changes: List[str] = []
    general_changes: List[str] = []
    conflicts: List[str] = []
    keep: List[str] = []
    archive: List[str] = []

    for rule in candidate_general:
        match = find_match(rule, old_general)
        if match:
            keep.append(f"[通用层] 保留旧规则：{match}")
            continue
        conflict_source = next((item for item in old_general if is_conflict(rule, item)), "")
        if conflict_source:
            conflicts.append(f"[通用层] 新规则“{rule}”与旧规则“{conflict_source}”存在冲突")
        else:
            added.append(f"[通用层] 新增：{rule}")
            general_changes.append(rule)

    for rule in candidate_personal:
        match = find_match(rule, old_personal)
        if match:
            keep.append(f"[个人层] 保留旧规则：{match}")
            continue
        conflict_source = next((item for item in old_personal if is_conflict(rule, item)), "")
        if conflict_source:
            conflicts.append(f"[个人层] 新规则“{rule}”与旧规则“{conflict_source}”存在冲突")
        else:
            added.append(f"[个人层] 新增：{rule}")
            personal_changes.append(rule)

    all_candidate_rules = list(candidate_general) + list(candidate_personal)
    for old_rule in old_general + old_personal:
        if not find_match(old_rule, all_candidate_rules, threshold=0.5):
            if any(marker in old_rule for marker in ("本次", "这次", "今天", "临时")):
                archive.append(f"建议归档旧的一次性规则：{old_rule}")

    overlap_ratio = len(keep) / max(len(candidate_general) + len(candidate_personal), 1)
    if conflicts and overlap_ratio < 0.4:
        action = "建议拆分为两个 skill：当前候选与旧 skill 的规则冲突较多，说明粒度或任务类型已经分化。"
    elif conflicts:
        action = "建议版本升级前先人工处理冲突：先确认哪些旧规则仍有效，再合并到新版本。"
    elif overlap_ratio >= 0.5:
        action = "建议版本升级：候选规则与旧 skill 高度相似，适合做增量更新。"
    elif archive:
        action = "建议归档旧 skill 中的临时规则，并保留稳定规则后再升级。"
    else:
        action = "建议保留旧 skill，同时把新候选作为并行草稿继续观察。"

    return {
        "skill_name": old_title,
        "new_items": format_bullets(added, "暂无明确新增内容"),
        "conflicting_items": format_bullets(conflicts, "暂无明显冲突"),
        "personal_items": format_bullets(personal_changes, "暂无新增的个性规则"),
        "general_items": format_bullets(general_changes, "暂无新增的通用规则"),
        "keep_items": format_bullets(keep, "暂无明确需要原样保留的旧规则"),
        "archive_items": format_bullets(archive, "暂无建议归档的旧规则"),
        "recommended_action": action,
    }


def main() -> None:
    args = parse_args()
    old_title, old_general, old_personal = extract_old_rules(args.old_skill)
    candidate = load_json(args.candidate)
    template = Path(args.template).read_text(encoding="utf-8")
    report = build_report(old_title, old_general, old_personal, candidate)

    content = template
    for key, value in {
        "{{skill_name}}": report["skill_name"],
        "{{new_items}}": report["new_items"],
        "{{conflicting_items}}": report["conflicting_items"],
        "{{personal_items}}": report["personal_items"],
        "{{general_items}}": report["general_items"],
        "{{keep_items}}": report["keep_items"],
        "{{archive_items}}": report["archive_items"],
        "{{recommended_action}}": report["recommended_action"],
    }.items():
        content = content.replace(key, value)

    if args.output:
        Path(args.output).write_text(content, encoding="utf-8")
    else:
        print(content)


if __name__ == "__main__":
    main()
