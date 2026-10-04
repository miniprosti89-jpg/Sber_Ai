import asyncio
import json
import os
import re
import uuid
import urllib.request
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, Cookie, Response, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response as FastAPIResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

# Хранилище сессий в памяти (session_id -> список жалоб)
SESSIONS: Dict[str, List[dict]] = {}

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")


class Complaint(BaseModel):
    text: str
    question: str = ""


class Text(BaseModel):
    text: str


def get_session_id(request: Request, response: Response) -> str:
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in SESSIONS:
        session_id = str(uuid.uuid4())
        response.set_cookie(key="session_id", value=session_id, httponly=True)
        SESSIONS[session_id] = []
    return session_id


def _ask_model_sync(complaints: list) -> str:
    """Асинхронный вызов Ollama через поток."""
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
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))["message"]["content"].strip()


# Красный уровень триажа (Экстренное состояние)
RED_PATTERNS = [
    r"боль\w* (в|за) (груди|грудин)", r"давит (в|за) (груди|грудин)", r"сердечн\w+ приступ", r"инфаркт",
    r"инсульт", r"перекосил[оа]? (лицо|рот)", r"(онемел|отнял)\w* (рука|нога|половина|лицо|лиц)",
    r"не могу (говорить|дышать|вдохнуть)", r"задыха\w+", r"нечем дышать", r"удуш",
    r"потерял\w* сознание", r"без сознания", r"обморок", r"судорог",
    r"сильн\w+ кровотечени", r"кровь не останавливается", r"кашляю кровью", r"рвота кровью",
    r"анафилакт", r"отёк\w* (горла|языка|гортани)", r"отек\w* (горла|языка|гортани)",
    r"отравил", r"хочу умереть", r"покончить с собой", r"суицид",
]
_red_re = re.compile("|".join(RED_PATTERNS), re.IGNORECASE)

# Желтый уровень триажа (Внимание / Полуэкстренное)
YELLOW_PATTERNS = [
    r"высокая температура", r"39\b", r"40\b", r"сильная боль в животе", r"острая боль",
    r"рвота", r"высокое давление", r"гипертонич", r"головокружен"
]
_yellow_re = re.compile("|".join(YELLOW_PATTERNS), re.IGNORECASE)

TRIAGE_PROMPT = (
    "Ты определяешь, описывает ли пациент ЭКСТРЕННОЕ, угрожающее жизни состояние. "
    "Ответь JSON: {\"emergency\": true} или {\"emergency\": false}."
)


def _llm_is_emergency_sync(text: str) -> bool:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": {"type": "object", "properties": {"emergency": {"type": "boolean"}}, "required": ["emergency"]},
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": TRIAGE_PROMPT},
            {"role": "user", "content": text},
        ],
    }
    req = urllib.request.Request(
        OLLAMA_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        content = json.loads(resp.read().decode("utf-8"))["message"]["content"]
    return bool(json.loads(content).get("emergency"))


@app.post("/api/triage")
async def triage(t: Text):
    """Определяет уровень риска: red (экстренно), yellow (внимание), green (планово)."""
    if _red_re.search(t.text):
        return {"level": "red", "emergency": True, "source": "rules"}

    if _yellow_re.search(t.text):
        return {"level": "yellow", "emergency": False, "source": "rules"}

    try:
        is_red = await asyncio.to_thread(_llm_is_emergency_sync, t.text)
        if is_red:
            return {"level": "red", "emergency": True, "source": "llm"}
    except Exception:
        pass

    return {"level": "green", "emergency": False}


@app.get("/")
async def read_index():
    return FileResponse("frontend/templates/index.html")


@app.post("/api/reset")
async def reset(request: Request, response: Response):
    sid = get_session_id(request, response)
    SESSIONS[sid] = []
    return {"count": 0}


@app.post("/api/complaints")
async def add_complaint(c: Complaint, request: Request, response: Response):
    sid = get_session_id(request, response)
    items = SESSIONS[sid]
    items.append({"n": len(items) + 1, "question": c.question, "complaint": c.text})

    try:
        question = await asyncio.to_thread(_ask_model_sync, items)
    except Exception as e:
        return {"count": len(items), "question": None, "error": f"Модель недоступна: {e}"}

    return {"count": len(items), "question": question}


@app.get("/api/soap")
async def get_soap_protocol(request: Request, response: Response):
    """Формирует структурированный SOAP-протокол для ЕМИАС."""
    sid = get_session_id(request, response)
    items = SESSIONS.get(sid, [])

    symptoms_text = "; ".join([it["complaint"] for it in items]) if items else "Жалобы не зафиксированы"

    soap_data = {
        "patient": "Вито Скаллето",
        "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "specialist": "Терапевт",
        "soap": {
            "S": f"Субъективные жалобы: {symptoms_text}.",
            "O": "Объективные данные: Состояние удовлетворительное. Первичный сбор проведен через ИИ-помощника.",
            "A": "Предварительное суждение: ОРИЗ / Функциональное расстройство (требует очного осмотра).",
            "P": "План действий: Очный прием терапевта, первичная лабораторная диагностика (ОАК, ОАМ)."
        },
        "items": items
    }
    return soap_data


@app.post("/api/ocr")
async def process_ocr(file: UploadFile = File(None)):
    """Симуляция OCR-модуля распознавания рецептов и справок."""
    await asyncio.sleep(1.2)  # имитация обработки файла
    return {
        "status": "success",
        "extracted_meds": [
            {"name": "💊 Амоксиклав 500мг", "schedule": "2 раза в день (после еды)"},
            {"name": "💧 Витамин C 1000мг", "schedule": "1 раз в день (утро)"}
        ]
    }


def _build_pdf_bytes(items: list) -> bytes:
    """Генерация PDF документа с поддержкой кириллицы."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
        from xml.sax.saxutils import escape

        font_name = "Helvetica"
        for reg_path in ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                         "/Library/Fonts/Arial.ttf"]:
            if os.path.exists(reg_path):
                pdfmetrics.registerFont(TTFont("CustomFont", reg_path))
                font_name = "CustomFont"
                break

        title_style = ParagraphStyle("t", fontName=font_name, fontSize=16, leading=22, spaceAfter=8)
        body_style = ParagraphStyle("b", fontName=font_name, fontSize=11, leading=16, spaceAfter=6)

        story = [
            Paragraph("<b>МЕДИЦИНСКИЙ ПРОТОКОЛ (ЕМИАС)</b>", title_style),
            Paragraph(f"Дата формирования: {datetime.now():%d.%m.%Y %H:%M}", body_style),
            Paragraph("<b>Пациент:</b> Вито Скаллето", body_style),
            Spacer(1, 10 * mm),
            Paragraph("<b>Собранный анамнез:</b>", body_style)
        ]
        for it in items:
            story.append(Paragraph(f"• <b>Вопрос:</b> {escape(it.get('question', ''))}", body_style))
            story.append(Paragraph(f"  <b>Ответ:</b> {escape(it.get('complaint', ''))}", body_style))
            story.append(Spacer(1, 3 * mm))

        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=20 * mm,
                                bottomMargin=20 * mm)
        doc.build(story)
        return buf.getvalue()
    except Exception:
        # Простой текстовый фоллбэк, если reportlab недоступен
        text = f"МЕДИЦИНСКИЙ ПРОТОКОЛ (ЕМИАС)\nДата: {datetime.now():%d.%m.%Y %H:%M}\n\n"
        for it in items:
            text += f"В: {it.get('question', '')}\nО: {it.get('complaint', '')}\n\n"
        return text.encode('utf-8')


@app.get("/api/protocol.pdf")
async def protocol_pdf(request: Request, response: Response):
    sid = get_session_id(request, response)
    items = SESSIONS.get(sid, [])
    pdf_content = await asyncio.to_thread(_build_pdf_bytes, items)
    return FastAPIResponse(
        content=pdf_content,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="protocol_emias.pdf"'}
    )