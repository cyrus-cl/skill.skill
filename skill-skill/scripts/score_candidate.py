#!/usr/bin/env python3
"""对候选 skill 做轻量评分。

使用示例：
    python score_candidate.py candidate.json -o score.json
    python score_candidate.py candidate.json --existing-skill old-skill.md
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", help="候选 skill JSON 路径")
    parser.add_argument("-o", "--output", help="评分结果输出路径")
    parser.add_argument("--existing-skill", help="已有 skill Markdown 路径，用于判断是否建议增量更新")
    return parser.parse_args()


def load_json(path: str) -> Dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalize(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def bigrams(text: str) -> set:
    cleaned = normalize(text)
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[index : index + 2] for index in range(len(cleaned) - 1)}


def jaccard_similarity(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 1.0
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def extract_old_skill_text(path: str) -> List[str]:
    lines = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```"):
            continue
        if line.startswith("#") or line.startswith("-"):
            lines.append(line.lstrip("#- ").strip())
    return lines


def similarity_score(candidate_rules: List[str], old_lines: List[str]) -> float:
    candidate_bigrams = set()
    old_bigrams = set()
    for item in candidate_rules:
        candidate_bigrams.update(bigrams(item))
    for item in old_lines:
        old_bigrams.update(bigrams(item))
    return jaccard_similarity(candidate_bigrams, old_bigrams)


def suggest_action(overall_score: float) -> str:
    if overall_score <= 3.0:
        return "不建议蒸馏"
    if overall_score <= 6.0:
        return "建议提醒用户，但暂不直接生成最终草稿"
    return "建议创建 skill 草稿"


def score_candidate(candidate: Dict[str, object], old_skill_path: Optional[str] = None) -> Dict[str, object]:
    repeated = candidate.get("repeated_tasks", [])
    corrections = candidate.get("frequent_corrections", [])
    stable = candidate.get("stable_output_requirements", [])
    general_rules = candidate.get("general_rules", [])
    personal_rules = candidate.get("personal_rules", [])
    one_off = candidate.get("suspected_one_off_exceptions", [])
    evidence = candidate.get("evidence_sources", [])
    confidence = float(candidate.get("confidence_score", 0.0))

    repetitiveness = min(10.0, len(repeated) * 2.5 + len(corrections) * 0.4)
    stability = min(10.0, len(stable) * 1.8 + confidence * 2.5)
    transferability = min(10.0, len(general_rules) * 1.2 + len(candidate.get("applicable_scenarios", [])) * 0.6 - len(one_off) * 0.8)
    personalization = min(10.0, len(personal_rules) * 2.0 + sum(1 for rule in personal_rules if "我" in rule) * 0.5)
    misdistillation_risk = min(
        10.0,
        len(one_off) * 1.8 + max(0, len(general_rules) - len(evidence)) * 0.6 + (2.0 if confidence < 0.45 else 0.0),
    )
    overall = round(
        (
            repetitiveness
            + stability
            + transferability
            + personalization
            + (10.0 - misdistillation_risk)
        )
        / 5.0,
        2,
    )

    suggested_action = suggest_action(overall)
    reasoning = [
        f"重复任务 {len(repeated)} 项，高频纠偏 {len(corrections)} 项。",
        f"稳定输出要求 {len(stable)} 项，个人规则 {len(personal_rules)} 项。",
        f"疑似当次特例 {len(one_off)} 项，解释来源 {len(evidence)} 条。",
    ]

    result = {
        "skill_name": candidate.get("skill_name", ""),
        "dimension_scores": {
            "repetitiveness": round(repetitiveness, 2),
            "stability": round(stability, 2),
            "transferability": round(transferability, 2),
            "personalization": round(personalization, 2),
            "misdistillation_risk": round(misdistillation_risk, 2),
        },
        "overall_score": overall,
        "suggested_action": suggested_action,
        "reasoning": reasoning,
    }

    if old_skill_path:
        old_lines = extract_old_skill_text(old_skill_path)
        similarity = similarity_score(list(general_rules) + list(personal_rules) + list(stable), old_lines)
        result["similar_existing_skill"] = {
            "path": old_skill_path,
            "similarity": round(similarity, 2),
        }
        if similarity >= 0.55:
            result["suggested_action"] = "建议增量更新旧 skill"
            result["reasoning"].append("检测到与旧 skill 高度相似，优先建议做增量更新。")
        elif 0.35 <= similarity < 0.55:
            result["reasoning"].append("与旧 skill 有部分重叠，建议人工确认是否要拆分或并行保留。")

    return result


def main() -> None:
    args = parse_args()
    result = score_candidate(load_json(args.candidate), args.existing_skill)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
