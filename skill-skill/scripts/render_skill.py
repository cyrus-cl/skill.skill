#!/usr/bin/env python3
"""把候选 JSON 渲染成可读的 skill 草稿 Markdown。

使用示例：
    python render_skill.py candidate.json --template ../assets/skill_template.md -o skill-draft.md
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", help="候选 skill JSON 路径")
    parser.add_argument("--template", required=True, help="skill_template.md 路径")
    parser.add_argument("-o", "--output", help="渲染后的 Markdown 输出路径")
    parser.add_argument("--source-label", help="用于写入维护记录的来源摘要")
    return parser.parse_args()


def load_json(path: str) -> Dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def format_bullets(items: Iterable[str], fallback: str = "未明确提取") -> str:
    values = [item.strip() for item in items if item and item.strip()]
    if not values:
        return f"- {fallback}"
    return "\n".join(f"- {item}" for item in values)


def format_numbered(items: Iterable[str], fallback: str = "补充明确的执行步骤") -> str:
    values = [item.strip() for item in items if item and item.strip()]
    if not values:
        return f"1. {fallback}"
    return "\n".join(f"{index}. {item}" for index, item in enumerate(values, start=1))


def join_inline(items: Iterable[str], fallback: str = "未明确提取") -> str:
    values = [item.strip() for item in items if item and item.strip()]
    return "；".join(values) if values else fallback


def bucket_personal_rules(rules: List[str]) -> Dict[str, List[str]]:
    buckets = {"tone": [], "structure": [], "banned": [], "rigor": [], "other": []}
    for rule in rules:
        if any(keyword in rule for keyword in ("文风", "语气", "简洁", "专业", "直接", "口语")):
            buckets["tone"].append(rule)
        elif any(keyword in rule for keyword in ("先", "结构", "顺序", "编号", "模块", "四段")):
            buckets["structure"].append(rule)
        elif any(keyword in rule for keyword in ("禁用", "不要写", "不要", "禁止", "别")):
            buckets["banned"].append(rule)
        elif any(keyword in rule for keyword in ("来源", "证据", "依据", "风险", "测试", "验收")):
            buckets["rigor"].append(rule)
        else:
            buckets["other"].append(rule)
    return buckets


def render_example(candidate: Dict[str, object]) -> str:
    skill_name = candidate.get("skill_name", "Workflow Skill")
    scenarios = candidate.get("applicable_scenarios", [])
    scenario = scenarios[0] if scenarios else "同类任务"
    return "\n".join(
        [
            "输入示例：",
            f"- 提供一份包含多轮纠偏的 {skill_name} transcript",
            f"- 当前任务属于：{scenario}",
            "",
            "输出示例：",
            "- 先给出通用层规则与个人层规则的分离结果",
            "- 再给出执行步骤、输出规范、负面约束与规则来源",
            "- 明确标注哪些内容属于当次特例，不能直接固化",
        ]
    )


def render_sources(candidate: Dict[str, object]) -> str:
    grouped = defaultdict(list)
    for item in candidate.get("evidence_sources", []):
        grouped[item["rule"]].append(item["source"])

    lines = ["## 规则来源"]
    for rule, sources in grouped.items():
        lines.append(f"- 规则：{rule}")
        for source in sources:
            lines.append(f"  来源：{source}")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    candidate = load_json(args.candidate)
    template = Path(args.template).read_text(encoding="utf-8")
    personal_buckets = bucket_personal_rules(candidate.get("personal_rules", []))
    source_label = args.source_label or candidate.get("source_transcript", "当前会话 transcript")

    replacements = {
        "{{skill_name}}": candidate.get("skill_name", "Workflow Skill"),
        "{{one_line_description}}": candidate.get("one_line_description", "从多轮对话中沉淀可复用工作流。"),
        "{{适用场景列表}}": format_bullets(candidate.get("applicable_scenarios", [])),
        "{{不适用场景列表}}": format_bullets(candidate.get("not_applicable_scenarios", [])),
        "{{用户需要提供的输入内容}}": format_bullets(
            [
                "当前任务的 transcript 或本次对话摘要",
                "与任务相关的输入材料或目标输出对象",
                "如需合并，额外提供已有 skill Markdown 文件",
            ]
        ),
        "{{通用的行业标准、框架、方法论}}": format_bullets(candidate.get("general_rules", [])),
        "{{例如：简洁、专业、避免口语化}}": join_inline(personal_buckets["tone"]),
        "{{例如：先结论后论据、用数字编号}}": join_inline(personal_buckets["structure"]),
        '{{例如：禁止使用"赋能"、"抓手"等词汇}}': join_inline(personal_buckets["banned"]),
        "{{例如：所有数据必须标注来源}}": join_inline(personal_buckets["rigor"]),
        "{{其他个人习惯}}": join_inline(personal_buckets["other"]),
        "{{长期可复用规则}}": format_bullets(candidate.get("general_rules", []) + candidate.get("personal_rules", [])),
        "{{当次特例列表}}": format_bullets(candidate.get("suspected_one_off_exceptions", []), fallback="未检测到明确的当次特例"),
        "{{分步骤的工作流程}}": format_numbered(candidate.get("execution_steps", [])),
        "{{详细的输出格式要求}}": format_bullets(candidate.get("stable_output_requirements", [])),
        "{{绝对不能做的事情}}": format_bullets(candidate.get("negative_constraints", [])),
        "{{一个完整的输入输出示例}}": render_example(candidate),
        "{{date}}": date.today().isoformat(),
        "{{对话链接或摘要}}": str(source_label),
        "{{下次更新建议}}": "当连续两次以上新增同类纠偏时，重新运行蒸馏并评估是否升级版本。",
        "{{后续维护建议}}": format_bullets(
            [
                "先用确认模板删除误提取规则，再决定是否创建最终 skill。",
                "如果未来出现相似旧 skill，优先运行 merge_candidate.py 做增量合并。",
                "如果连续 3 次使用仍需新增同类规则，说明当前版本仍需继续迭代。",
            ]
        ),
    }

    content = template
    for key, value in replacements.items():
        content = content.replace(key, value)

    content += "\n\n" + render_sources(candidate) + "\n"

    if args.output:
        Path(args.output).write_text(content, encoding="utf-8")
    else:
        print(content)


if __name__ == "__main__":
    main()
