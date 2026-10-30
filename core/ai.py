"""AI dựng kịch bản automation từ lời (gap #3b).

generate_workflow(task, call_llm) tách khỏi HTTP -> test được (call_llm injectable).
Provider thật: OpenAI-compatible (chat/completions, dùng được OpenAI/OpenRouter/local/Groq…)
hoặc Gemini. Xuất mảng JSON bước, validate bằng automation.validate_script, có 1 vòng tự sửa.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from . import automation

_SYSTEM = """Bạn là trợ lý sinh kịch bản automation trình duyệt cho PinkAgc Browser.
CHỈ xuất một mảng JSON các bước — không giải thích, không markdown.
Mỗi bước là object có "action" + tham số. Selector dùng CSS hoặc XPath.
Biến: lưu bằng set_var/extract/http_request/gen_2fa…, chèn bằng {{ten}} trong mọi tham số chuỗi.
Control-flow lồng nhau bằng "body" (loop/foreach/while_exists) hoặc "then"/"else" (if):
  {"action":"loop","times":3,"body":[ ... ]}
  {"action":"foreach","file":"accs.txt","var":"acc","body":[ ... ]}
  {"action":"if","left":"{{x}}","op":"==","right":"1","then":[ ... ],"else":[ ... ]}
Các action hợp lệ (tên + tham số bắt buộc):
{ACTIONS}"""


def _action_ref() -> str:
    out = []
    for a, req in automation._ACTIONS.items():
        out.append(f"- {a}" + (f" (bắt buộc: {', '.join(req)})" if req else ""))
    return "\n".join(out)


def build_messages(task: str, errors: list[str] | None = None) -> list[dict]:
    msgs = [{"role": "system", "content": _SYSTEM.replace("{ACTIONS}", _action_ref())},
            {"role": "user", "content": f"Việc cần làm: {task}\nXuất mảng JSON các bước."}]
    if errors:
        msgs.append({"role": "user", "content": "Kịch bản trước lỗi validate:\n"
                     + "\n".join(errors) + "\nSửa lại, CHỈ xuất JSON."})
    return msgs


def extract_steps(text: str | None) -> list | None:
    """Rút mảng JSON bước từ câu trả lời LLM (bỏ fence ```json, lấy [ ... ] ngoài cùng)."""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    raw = m.group(1) if m else text
    i, j = raw.find("["), raw.rfind("]")
    if i < 0 or j < 0 or j < i:
        return None
    try:
        v = json.loads(raw[i:j + 1])
    except (ValueError, TypeError):
        return None
    return v if isinstance(v, list) else None


def generate_workflow(task: str, call_llm: Callable[[list], str]) -> dict:
    """call_llm(messages)->text. Trả {steps} hoặc {error, raw?, steps?}. Có 1 vòng tự sửa khi validate fail."""
    if not task or not task.strip():
        return {"error": "Chưa nhập việc cần làm"}
    try:
        raw = call_llm(build_messages(task))
    except Exception as e:  # noqa: BLE001
        return {"error": f"Gọi AI lỗi: {e}"}
    steps = extract_steps(raw)
    if steps is None:
        return {"error": "AI không trả JSON hợp lệ", "raw": raw}
    errs = automation.validate_script(steps)
    if errs:
        try:                                              # 1 vòng sửa theo lỗi validate
            raw2 = call_llm(build_messages(task, errs))
            steps2 = extract_steps(raw2)
            if steps2 is not None and not automation.validate_script(steps2):
                return {"steps": steps2, "raw": raw2}
        except Exception:  # noqa: BLE001
            pass
        return {"error": "Kịch bản AI sinh ra không hợp lệ: " + "; ".join(errs[:5]),
                "steps": steps, "raw": raw}
    return {"steps": steps, "raw": raw}


def call_llm_http(settings: dict, messages: list[dict]) -> str:
    """Gọi provider thật. OpenAI-compatible hoặc Gemini. Cần ai_key trong settings."""
    import urllib.request
    key = settings.get("ai_key", "")
    if not key:
        raise RuntimeError("Chưa cấu hình API key AI (Cài đặt → AI)")
    model = settings.get("ai_model", "")
    if settings.get("ai_provider") == "gemini":
        model = model or "gemini-2.0-flash"
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
               f":generateContent?key={key}")
        text = "\n\n".join(m["content"] for m in messages)
        body = {"contents": [{"parts": [{"text": text}]}]}
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            d = json.loads(r.read())
        return d["candidates"][0]["content"]["parts"][0]["text"]
    base = (settings.get("ai_base_url") or "https://api.openai.com/v1").rstrip("/")
    body = {"model": model or "gpt-4o-mini", "messages": messages, "temperature": 0.2}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"]


if __name__ == "__main__":
    good = '[{"action":"goto","url":"https://x.com"},{"action":"click","selector":"#go"}]'
    assert extract_steps("```json\n" + good + "\n```") == json.loads(good)
    assert extract_steps("Đây nhé:\n" + good + "\nxong") == json.loads(good)
    assert extract_steps("không có json ở đây") is None
    assert generate_workflow("mở x rồi click", lambda m: good).get("steps")
    assert generate_workflow("", lambda m: good).get("error")               # task rỗng
    assert generate_workflow("x", lambda m: '[{"action":"nope"}]').get("error")  # action lạ
    seq = iter(['[{"action":"nope"}]', good])                               # sai -> sửa -> đúng
    r = generate_workflow("x", lambda m: next(seq))
    assert r.get("steps") and not r.get("error"), r
    assert _SYSTEM.replace("{ACTIONS}", _action_ref()).count("gen_2fa") >= 1  # catalog có action thật
    print("OK - ai.py extract/generate/repair/catalog - PASS")
