import json
import os
import urllib.request
from pathlib import Path
from threading import Lock

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
COMPLAINTS_FILE = Path(__file__).parent / "complaints.json"
MAX_COMPLAINTS = 3

_lock = Lock()

# Подключаем статические файлы (CSS, JS)
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")


class Complaint(BaseModel):
    text: str
    question: str = ""


def _load() -> list:
    if COMPLAINTS_FILE.exists():
        return json.loads(COMPLAINTS_FILE.read_text(encoding="utf-8"))
    return []


def _save(items: list) -> None:
    COMPLAINTS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def ask_model(complaints: list) -> str:
    """Просит qwen2.5:3b (через Ollama) придумать следующий уточняющий вопрос."""
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты медицинский ИИ-помощник, собирающий анамнез перед приёмом у терапевта. "
                    "Тебе дают JSON со всеми жалобами пациента. Придумай ОДИН следующий вопрос "
                    "пациенту, который поможет уточнить его состояние (длительность, "
                    "интенсивность, сопутствующие симптомы, принимаемые лекарства и т.п.). "
                    "Не повторяй уже заданные вопросы. Не ставь диагнозов. "
                    "Отвечай по-русски, только текстом вопроса, без пояснений."
                ),
            },
            {"role": "user", "content": json.dumps(complaints, ensure_ascii=False, indent=2)},
        ],
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))["message"]["content"].strip()


@app.get("/")
def read_index():
    return FileResponse("frontend/templates/index.html")


@app.post("/api/reset")
def reset():
    with _lock:
        _save([])
    return {"count": 0}


@app.post("/api/complaints")
def add_complaint(c: Complaint):
    """Логирует подтверждённую жалобу в JSON и, пока их меньше трёх, просит модель задать следующий вопрос."""
    with _lock:
        items = _load()
        if len(items) < MAX_COMPLAINTS:
            items.append({"n": len(items) + 1, "question": c.question, "complaint": c.text})
            _save(items)

    done = len(items) >= MAX_COMPLAINTS
    if done:
        return {"count": len(items), "done": True, "question": None}

    try:
        question = ask_model(items)
    except Exception as e:
        return {"count": len(items), "done": False, "question": None, "error": f"Модель недоступна: {e}"}
    return {"count": len(items), "done": False, "question": question}
