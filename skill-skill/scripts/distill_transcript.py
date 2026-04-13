#!/usr/bin/env python3
"""从 Markdown 对话转录中提取候选 skill JSON。

设计目标：
1. 只依赖 Python 标准库。
2. 保持启发式逻辑可解释、可修改，不假装具备隐藏能力。
3. 输出既适合人工复核，也适合后续脚本继续处理。

使用示例：
    python distill_transcript.py transcript.md -o candidate.json
    python distill_transcript.py transcript.md --pretty
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


ROUND_RE = re.compile(r"^##\s*第\s*(\d+)\s*轮\s*$", re.MULTILINE)
SPEAKER_RE = re.compile(r"^###\s*(用户|助手)\s*$", re.MULTILINE)
SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")

CORRECTION_MARKERS = (
    "不要",
    "改成",
    "改为",
    "补充",
    "补上",
    "统一",
    "必须",
    "需要",
    "请按",
    "别",
    "去掉",
    "删掉",
    "固定成",
    "统一用",
)
PERSONAL_MARKERS = (
    "我习惯",
    "我更喜欢",
    "我的",
    "我希望",
    "按我的",
    "以后都按这个",
    "文风",
    "语气",
    "禁用",
    "不要写",
)
NEGATIVE_MARKERS = ("不要", "禁止", "不能", "别", "避免", "不看", "不写", "先忽略")
ONE_OFF_MARKERS = ("这次", "本次", "这版", "今天", "当前", "这个客户", "这个项目", "暂时", "先忽略")

TAG_KEYWORDS = {
    "structure": ("结构", "四段", "模块", "顺序", "编号", "先写", "章节", "固定成"),
    "format": ("格式", "模板", "表格", "长文", "散文", "输出", "统一用", "编号"),
    "scope": ("范围", "in scope", "out of scope", "边界", "不看", "只看", "只改"),
    "tone": ("文风", "语气", "简洁", "专业", "直接", "口语", "形容词"),
    "evidence": ("来源", "证据", "假设", "依据", "数据"),
    "risk": ("风险", "异常", "回归", "事务", "依赖", "影响"),
    "testing": ("测试", "测试缺口", "验收"),
    "commit": ("提交信息", "commit", "Conventional Commits", "scope"),
    "dimension": ("维度", "定价", "渠道", "目标用户", "差异", "检查表"),
}

DOMAIN_PROFILES = {
    "competitor": {
        "name": "Competitor Analysis Workflow",
        "description": "从竞品分析对话中抽取稳定的结构、分析维度、结论口径与输出格式，生成可复用的竞品分析 skill 草稿。",
        "keywords": ("竞品", "对标", "分析", "定价", "渠道", "目标用户"),
        "applicable": [
            "需要多次迭代竞品分析结构与维度的产品或市场研究任务",
            "希望把竞品写作框架与个人结论口径长期固定下来",
            "需要统一多家竞品的对比顺序和输出格式",
        ],
        "not_applicable": [
            "一次性市场摘录或资料搬运",
            "只需要罗列功能点，不做结构化判断",
            "仅针对某个客户的临时竞标材料",
            "缺少可复用分析维度的临时任务",
            "仍在频繁推翻分析结构的早期探索阶段",
        ],
        "steps": [
            "明确竞品范围与本次排除项。",
            "固定每家竞品的分析顺序与公共维度。",
            "先给一句结论，再展开差异、风险与可借鉴点。",
            "统一编号和格式，确保不同竞品可横向比较。",
        ],
    },
    "prd": {
        "name": "PRD Writing Workflow",
        "description": "从 PRD 写作对话中抽取稳定的文档结构、个人文风、禁用表达和验收口径，生成可复用的 PRD skill 草稿。",
        "keywords": ("PRD", "需求", "验收", "范围", "风险", "依赖"),
        "applicable": [
            "需要反复校准 PRD 结构、语气和验收口径的产品文档任务",
            "希望把个人 PRD 写作顺序、禁用表达和范围定义固化下来",
            "需要长期统一需求文档的编号、范围边界和风险章节",
        ],
        "not_applicable": [
            "只写一次性的活动方案或脑暴提纲",
            "没有明确输入材料的空白 PRD 请求",
            "仍在频繁改变核心文档结构的探索阶段",
            "只想保存某个措辞，而不是完整文档工作流",
            "强依赖本次业务背景且不可迁移的临时说明",
        ],
        "steps": [
            "先收敛目标、用户问题、范围和验收标准。",
            "把范围拆成 in scope 与 out of scope。",
            "单列风险、依赖和关键指标来源。",
            "按既定文风和禁用表达清理整篇文档。",
        ],
    },
    "code-review": {
        "name": "Python Code Review Workflow",
        "description": "从代码审查对话中抽取稳定的审查顺序、风险优先级、测试关注点与提交信息规范，生成可复用的代码审查 skill 草稿。",
        "keywords": ("代码审查", "review", "Python", "PR", "测试", "提交信息"),
        "applicable": [
            "需要多轮校准 Python 代码审查口径、严重级别和输出格式",
            "希望固定风险优先、测试导向的 review 工作流",
            "需要把提交信息规范与审查重点一起沉淀为长期规则",
        ],
        "not_applicable": [
            "只做一次性的代码解释或教学说明",
            "没有代码或 diff 的泛泛审查请求",
            "只想修饰表达，不涉及真实风险判断",
            "以 UI 文案润色为主的非工程审查任务",
            "仍在频繁切换审查重点、顺序和输出格式的探索阶段",
        ],
        "steps": [
            "先看行为风险和回归风险，再看风格问题。",
            "按严重级别排序审查结论，并给出影响与修复建议。",
            "重点检查测试缺口、异常处理和事务边界。",
            "补充符合规范的提交信息建议。",
        ],
    },
}


@dataclass
class Round:
    index: int
    user: str
    assistant: str


@dataclass
class RuleRecord:
    text: str
    round_index: int
    source_excerpt: str
    tags: List[str]
    is_correction: bool
    is_personal: bool
    is_negative: bool
    is_one_off: bool
    is_meta: bool
    is_seed_request: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", help="Markdown 对话转录文件路径")
    parser.add_argument("-o", "--output", help="候选 JSON 输出路径")
    parser.add_argument("--pretty", action="store_true", help="以缩进格式打印 JSON")
    return parser.parse_args()


def parse_transcript(text: str) -> List[Round]:
    if ROUND_RE.search(text):
        return _parse_structured_transcript(text)
    return _parse_line_transcript(text)


def _parse_structured_transcript(text: str) -> List[Round]:
    rounds: List[Round] = []
    matches = list(ROUND_RE.finditer(text))
    for index, match in enumerate(matches):
        round_index = int(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        speaker_parts = SPEAKER_RE.split(block)
        speaker_map: Dict[str, str] = {"用户": "", "助手": ""}
        for offset in range(1, len(speaker_parts), 2):
            speaker = speaker_parts[offset].strip()
            content = speaker_parts[offset + 1].strip()
            speaker_map[speaker] = content
        rounds.append(Round(round_index, speaker_map["用户"], speaker_map["助手"]))
    return rounds


def _parse_line_transcript(text: str) -> List[Round]:
    rounds: List[Round] = []
    current_user: List[str] = []
    current_assistant: List[str] = []
    current_index = 1
    current_speaker = None

    def flush() -> None:
        nonlocal current_user, current_assistant, current_index
        if current_user or current_assistant:
            rounds.append(
                Round(
                    current_index,
                    "\n".join(current_user).strip(),
                    "\n".join(current_assistant).strip(),
                )
            )
            current_index += 1
            current_user = []
            current_assistant = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("用户:"):
            if current_speaker == "用户" and current_user:
                flush()
            current_speaker = "用户"
            current_user.append(line[3:].strip())
        elif line.startswith("助手:"):
            current_speaker = "助手"
            current_assistant.append(line[3:].strip())
        elif current_speaker == "用户":
            current_user.append(line)
        elif current_speaker == "助手":
            current_assistant.append(line)
    flush()
    return rounds


def clean_rule_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    return text.strip("-*0123456789. ")


def sentence_iter(text: str) -> Iterable[str]:
    for part in SENTENCE_SPLIT_RE.split(text):
        sentence = clean_rule_text(part)
        if len(sentence) >= 5:
            yield sentence


def normalize(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def classify_tags(sentence: str) -> List[str]:
    tags = []
    for tag, keywords in TAG_KEYWORDS.items():
        if any(keyword.lower() in sentence.lower() for keyword in keywords):
            tags.append(tag)
    return tags or ["general"]


def short_excerpt(text: str, limit: int = 60) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_rule_records(rounds: Sequence[Round]) -> List[RuleRecord]:
    records: List[RuleRecord] = []
    for item in rounds:
        for sentence in sentence_iter(item.user):
            tone_like = any(word in sentence for word in ("文风", "语气", "简洁", "专业", "直接", "短句", "形容词", "口语"))
            is_seed_request = item.index == 1 and sentence.startswith(("帮我", "请帮我", "先出个"))
            is_meta = any(marker in sentence for marker in ("结构稳定了", "可以沉淀", "具备复用条件"))
            records.append(
                RuleRecord(
                    text=sentence,
                    round_index=item.index,
                    source_excerpt=short_excerpt(sentence),
                    tags=classify_tags(sentence),
                    is_correction=any(marker in sentence for marker in CORRECTION_MARKERS),
                    is_personal=any(marker in sentence for marker in PERSONAL_MARKERS)
                    or sentence.startswith(("我习惯", "我的", "我更喜欢", "我做", "我写"))
                    or ("我" in sentence and any(word in sentence for word in ("习惯", "喜欢", "要求", "统一", "会特别看")))
                    or tone_like,
                    is_negative=any(marker in sentence for marker in NEGATIVE_MARKERS),
                    is_one_off=any(marker in sentence for marker in ONE_OFF_MARKERS),
                    is_meta=is_meta,
                    is_seed_request=is_seed_request,
                )
            )
    return records


def infer_profile(rounds: Sequence[Round]) -> Dict[str, object]:
    combined = " ".join(f"{item.user} {item.assistant}" for item in rounds)
    scores = {}
    for key, profile in DOMAIN_PROFILES.items():
        scores[key] = sum(combined.lower().count(word.lower()) for word in profile["keywords"])
    best_domain = max(scores, key=scores.get)
    if scores[best_domain] == 0:
        return {
            "name": "Reusable Workflow Skill",
            "description": "从多轮对话中抽取稳定的任务结构、个人偏好和输出规则，生成可复用的工作流 skill 草稿。",
            "applicable": [
                "同类任务经过多轮纠偏后逐渐稳定",
                "用户希望把结构、格式和风格要求沉淀下来",
            ],
            "not_applicable": [
                "只有一次性上下文，没有长期可迁移方法",
                "用户仍在频繁改方向，规则尚未稳定",
                "只想收藏零散提示词或表述片段",
                "缺少 transcript 或当前会话上下文",
                "需要跨会话历史才能判断规则来源",
            ],
            "steps": [
                "识别重复纠偏与稳定输出要求。",
                "拆分通用规则、个人规则和当次特例。",
                "生成候选 skill 草稿并保留来源说明。",
            ],
        }
    return DOMAIN_PROFILES[best_domain]


def dedupe_rules(records: Iterable[RuleRecord]) -> List[RuleRecord]:
    seen = set()
    results = []
    for record in records:
        key = normalize(record.text)
        if key and key not in seen:
            seen.add(key)
            results.append(record)
    return results


def select_rules(records: Sequence[RuleRecord], predicate, limit: int = 8) -> List[RuleRecord]:
    return dedupe_rules(
        [
            record
            for record in records
            if predicate(record) and not record.is_seed_request and not record.is_meta
        ]
    )[:limit]


def infer_repeated_tasks(records: Sequence[RuleRecord]) -> List[str]:
    tag_counts = Counter(tag for record in records for tag in record.tags)
    labels = {
        "structure": "重复校准任务结构与顺序",
        "format": "重复统一输出格式与排版",
        "tone": "重复收敛文风、语气和表达方式",
        "dimension": "重复补充分析维度或检查维度",
        "risk": "重复强调风险、依赖或行为影响",
        "testing": "重复强调测试与验收检查",
        "commit": "重复统一提交信息规范",
        "scope": "重复校准范围边界与排除项",
        "evidence": "重复要求来源、证据或假设说明",
    }
    tasks = [labels[tag] for tag, count in tag_counts.items() if count >= 2 and tag in labels]
    return tasks[:6] or ["同类任务中存在重复纠偏与规则收敛"]


def stable_requirements(records: Sequence[RuleRecord], last_round: int) -> List[RuleRecord]:
    tag_counts = Counter(tag for record in records for tag in record.tags)

    def predicate(record: RuleRecord) -> bool:
        recent = record.round_index >= max(1, last_round - 2)
        repeated_theme = any(tag_counts[tag] >= 2 for tag in record.tags)
        return not record.is_one_off and (recent or repeated_theme)

    return select_rules(records, predicate, limit=8)


def build_evidence(records: Sequence[RuleRecord]) -> List[Dict[str, str]]:
    return [
        {
            "rule": record.text,
            "source": f"对话第{record.round_index}轮：用户说“{record.source_excerpt}”",
        }
        for record in records
    ]


def estimate_confidence(
    corrections: Sequence[RuleRecord],
    stable: Sequence[RuleRecord],
    personal: Sequence[RuleRecord],
    one_off: Sequence[RuleRecord],
) -> float:
    correction_score = min(len(corrections) / 4.0, 1.0)
    stable_score = min(len(stable) / 4.0, 1.0)
    personal_score = min(len(personal) / 3.0, 1.0)
    one_off_penalty = min(len(one_off) / max(len(corrections) + len(stable) + 1, 1), 1.0)
    score = (0.35 * correction_score) + (0.3 * stable_score) + (0.2 * personal_score) + (0.15 * (1 - one_off_penalty))
    return round(score, 2)


def build_execution_steps(profile: Dict[str, object], general_records: Sequence[RuleRecord]) -> List[str]:
    steps = list(profile["steps"])
    if any("evidence" in record.tags for record in general_records):
        steps.append("为关键判断补上来源、证据或假设说明。")
    return steps[:6]


def main() -> None:
    args = parse_args()
    transcript_path = Path(args.transcript)
    rounds = parse_transcript(transcript_path.read_text(encoding="utf-8"))
    if not rounds:
        raise SystemExit("未解析到任何对话轮次，请检查 transcript 格式。")

    profile = infer_profile(rounds)
    records = build_rule_records(rounds)
    last_round = max(item.index for item in rounds)

    correction_records = select_rules(records, lambda item: item.is_correction, limit=10)
    personal_records = select_rules(records, lambda item: item.is_personal and not item.is_one_off, limit=8)
    one_off_records = select_rules(records, lambda item: item.is_one_off, limit=8)
    general_records = select_rules(records, lambda item: (not item.is_personal) and (not item.is_one_off), limit=10)
    negative_records = select_rules(records, lambda item: item.is_negative, limit=8)
    stable_records = stable_requirements(records, last_round)
    execution_steps = build_execution_steps(profile, general_records)

    candidate = {
        "skill_name": profile["name"],
        "one_line_description": profile["description"],
        "confidence_score": estimate_confidence(correction_records, stable_records, personal_records, one_off_records),
        "applicable_scenarios": profile["applicable"],
        "not_applicable_scenarios": profile["not_applicable"],
        "repeated_tasks": infer_repeated_tasks(records),
        "frequent_corrections": [item.text for item in correction_records],
        "stable_output_requirements": [item.text for item in stable_records],
        "general_rules": [item.text for item in general_records],
        "personal_rules": [item.text for item in personal_records],
        "suspected_one_off_exceptions": [item.text for item in one_off_records],
        "execution_steps": execution_steps,
        "negative_constraints": [item.text for item in negative_records],
        "evidence_sources": build_evidence(
            dedupe_rules(list(general_records) + list(personal_records) + list(one_off_records) + list(negative_records))
        ),
        "source_transcript": str(transcript_path),
        "round_count": len(rounds),
    }

    output = json.dumps(candidate, ensure_ascii=False, indent=2 if args.pretty or args.output else 2)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
