"""MBTI personality test API — single LLM call approach."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from loguru import logger

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionMessageParam

router = APIRouter(prefix="/mbti", tags=["mbti"])

_questions: list[dict[str, Any]] | None = None


def _load_questions() -> list[dict[str, Any]]:
    global _questions
    if _questions is not None:
        return _questions
    path = Path("config/mbti_questions.json")
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        loaded: list[dict[str, Any]] = data["questions"]
    else:
        loaded = []
    _questions = loaded
    return loaded


@router.get("/questions")
async def get_questions() -> dict[str, Any]:
    """Return all MBTI questions."""
    questions = _load_questions()
    return {"total": len(questions), "questions": questions}


@router.post("/run")
async def run_test(request: Request) -> dict[str, Any]:
    """Run the full MBTI test via a single LLM call."""
    ctx = getattr(request.app.state, "default_context_cache", None)
    if ctx is None or ctx.agent_engine is None:
        return {"error": "后端未就绪，请先启动后端"}

    questions = _load_questions()
    if not questions:
        return {"error": "题库为空"}

    logger.info("[MBTI] 开始性格测试，共 {} 题", len(questions))

    question_lines: list[str] = []
    for q in questions:
        question_lines.append(f"{q['id']}. {q['text']}\n   A: {q['a']}\n   B: {q['b']}")

    test_prompt = (
        "请你以自己的性格和价值观，认真回答以下 MBTI 性格测试的每一道题。\n"
        "每题选择 A 或 B，并用一句话简短说明理由。\n\n"
        "请严格按照以下 JSON 格式输出，不要输出其他内容：\n"
        '{"answers": [{"id": 1, "choice": "a", "reason": "..."}, ...]}\n\n'
        "题目：\n\n" + "\n\n".join(question_lines)
    )

    persona_text = ""
    profile_path_str = ctx.lab_setting.agent.memory_agent_profile
    if profile_path_str:
        from lab.profile.schema import Profile

        profile_path = Path(profile_path_str)
        if not profile_path.is_absolute():
            profile_path = Path(ctx.lab_setting.root.root_dir) / profile_path
        if profile_path.exists():
            profile = Profile.from_toml(profile_path)
            if profile.prompt.persona:
                persona_file = Path(ctx.lab_setting.root.root_dir) / profile.prompt.persona
                if persona_file.exists():
                    persona_text = persona_file.read_text(encoding="utf-8").strip()

    from lab.agent.stateless_llm_factory import LLMFactory

    chat_model = ctx.lab_setting.agent.chat_model
    chat_llm_config = ctx.lab_setting.agent.llm.get_provider_config(chat_model.llm_provider)
    llm = LLMFactory.create_llm(
        model=chat_model.llm_model_name,
        base_url=chat_llm_config.llm_base_url,
        llm_api_key=chat_llm_config.llm_api_key,
    )

    messages: list[ChatCompletionMessageParam] = []
    if persona_text:
        messages.append({"role": "system", "content": persona_text})
    messages.append({"role": "user", "content": test_prompt})

    logger.info("[MBTI] 正在调用 LLM 进行答题（模型: {}）…", llm.model)
    try:
        response = await llm.client.chat.completions.create(
            model=llm.model,
            messages=messages,
            temperature=0.7,
        )
        raw_content = response.choices[0].message.content or ""
    except Exception as e:
        logger.error("[MBTI] LLM 调用失败: {}", e)
        return {"error": f"LLM 调用失败: {e}"}

    logger.info("[MBTI] LLM 回复完成，正在解析答案…")
    answers = _parse_llm_response(raw_content, questions)
    if answers is None:
        logger.error("[MBTI] 无法解析 LLM 回复")
        return {"error": "无法解析 LLM 回复", "raw": raw_content}

    logger.info("[MBTI] 解析成功，共 {} 题有效答案", len(answers))
    result = _calculate_result(questions, answers)
    # Enrich answers with question text for frontend preview
    enriched_answers: list[dict[str, Any]] = []
    for ans in answers:
        q = next((q for q in questions if q["id"] == ans["question_id"]), None)
        entry: dict[str, Any] = {**ans}
        if q:
            entry["question_text"] = q["text"]
            entry["option_a"] = q["a"]
            entry["option_b"] = q["b"]
        enriched_answers.append(entry)
    result["answers"] = enriched_answers

    # Persist to file
    _save_result_to_profile(ctx, result)

    logger.info("[MBTI] 测试完成！结果: {} — {}", result["type"], result["description"])
    return {"status": "completed", "result": result}


@router.get("/result")
async def get_result(request: Request) -> dict[str, Any]:
    """Get the latest test result for the current profile."""
    ctx = getattr(request.app.state, "default_context_cache", None)
    if ctx is not None:
        loaded = _load_result_from_profile(ctx)
        if loaded:
            return {"status": "completed", "result": loaded}

    return {"status": "not_tested"}


def _parse_llm_response(content: str, questions: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    content = content.strip()
    if "```" in content:
        parts = content.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                content = part
                break

    try:
        data = json.loads(content)
        raw_answers = data.get("answers", data) if isinstance(data, dict) else data
        if not isinstance(raw_answers, list):
            return None

        answers: list[dict[str, Any]] = []
        for item in raw_answers:
            qid = item.get("id")
            choice = str(item.get("choice", "")).lower().strip()
            reason = str(item.get("reason", ""))
            if qid is not None and choice in ("a", "b"):
                answers.append({"question_id": int(qid), "choice": choice, "reasoning": reason})

        if len(answers) < len(questions) // 2:
            return None
        return answers
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _calculate_result(questions: list[dict[str, Any]], answers: list[dict[str, Any]]) -> dict[str, Any]:
    scores: dict[str, int] = {"E": 0, "I": 0, "S": 0, "N": 0, "T": 0, "F": 0, "J": 0, "P": 0}

    for answer in answers:
        q = next((q for q in questions if q["id"] == answer["question_id"]), None)
        if q is None:
            continue
        pole = q["a_pole"] if answer["choice"] == "a" else q["b_pole"]
        scores[pole] += 1

    mbti_type = ""
    dimensions: dict[str, Any] = {}
    for pair in [("E", "I"), ("S", "N"), ("T", "F"), ("J", "P")]:
        a_score = scores[pair[0]]
        b_score = scores[pair[1]]
        winner = pair[0] if a_score >= b_score else pair[1]
        mbti_type += winner
        dimensions[f"{pair[0]}{pair[1]}"] = {
            pair[0]: a_score,
            pair[1]: b_score,
            "dominant": winner,
            "strength": abs(a_score - b_score),
        }

    return {
        "type": mbti_type,
        "dimensions": dimensions,
        "description": _MBTI_DESCRIPTIONS.get(mbti_type, f"{mbti_type} 类型"),
    }


_MBTI_DESCRIPTIONS: dict[str, str] = {
    "INTJ": "建筑师 — 富有想象力和战略性的思想家，一切皆在计划之中",
    "INTP": "逻辑学家 — 具有创造力的发明家，对知识有着止不住的渴望",
    "ENTJ": "指挥官 — 大胆、富有想象力且意志强大的领导者",
    "ENTP": "辩论家 — 聪明好奇的思想者，不会放弃任何智力上的挑战",
    "INFJ": "提倡者 — 安静而神秘，同时鼓舞人心且不知疲倦的理想主义者",
    "INFP": "调停者 — 诗意、善良的利他主义者，总是热心为正义事业提供帮助",
    "ENFJ": "主人公 — 富有魅力鼓舞人心的领导者，有能力使听众着迷",
    "ENFP": "竞选者 — 热情、有创造力、社交能力强的自由精灵",
    "ISTJ": "物流师 — 实际且注重事实的个人，可靠性不容怀疑",
    "ISFJ": "守卫者 — 非常专注而温暖的守护者，时刻准备着保护爱着的人",
    "ESTJ": "总经理 — 出色的管理者，在管理事情或人方面无与伦比",
    "ESFJ": "执政官 — 极有同情心、爱交际受欢迎的人，总是热心助人",
    "ISTP": "鉴赏家 — 大胆而实际的实验家，擅长使用各种形式的工具",
    "ISFP": "探险家 — 灵活有魅力的艺术家，时刻准备着探索和体验新事物",
    "ESTP": "企业家 — 聪明、精力充沛善于感知的人，真正享受冒险生活",
    "ESFP": "表演者 — 自发的、精力充沛的表演者，生活在他们周围永不无聊",
}


def _get_result_path(ctx: Any) -> Path | None:
    """Get the MBTI result file path for the current profile."""
    profile_path_str = ctx.lab_setting.agent.memory_agent_profile
    if not profile_path_str:
        return None
    profile_id = Path(profile_path_str).stem
    result_dir = Path("config/mbti_results")
    result_dir.mkdir(parents=True, exist_ok=True)
    return result_dir / f"{profile_id}.json"


def _save_result_to_profile(ctx: Any, result: dict[str, Any]) -> None:
    """Save MBTI result to a JSON file keyed by profile ID."""
    path = _get_result_path(ctx)
    if path is None:
        return
    try:
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug("[MBTI] 结果已保存到 {}", path)
    except Exception as e:
        logger.warning("[MBTI] 保存结果失败: {}", e)


def _load_result_from_profile(ctx: Any) -> dict[str, Any] | None:
    """Load MBTI result from the JSON file for the current profile."""
    path = _get_result_path(ctx)
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("[MBTI] 加载结果失败: {}", e)
        return None
