import json
import os
import re
import urllib.request
from datetime import datetime
from io import BytesIO
from pathlib import Path
from threading import Lock

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

app = FastAPI()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
COMPLAINTS_FILE = Path(__file__).parent / "complaints.json"

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


# Страховка: явные признаки неотложных состояний ловятся правилами, даже если модель недоступна или ошиблась
EMERGENCY_PATTERNS = [
    r"боль\w* (в|за) (груди|грудин)", r"давит (в|за) (груди|грудин)", r"сердечн\w+ приступ", r"инфаркт",
    r"инсульт", r"перекосил[оа]? (лицо|рот)", r"(онемел|отнял)\w* (рука|нога|половина|лицо|лиц)",
    r"не могу (говорить|дышать|вдохнуть)", r"задыха\w+", r"нечем дышать", r"удуш",
    r"потерял\w* сознание", r"без сознания", r"обморок", r"судорог",
    r"сильн\w+ кровотечени", r"кровь не останавливается", r"кашляю кровью", r"рвота кровью",
    r"анафилакт", r"отёк\w* (горла|языка|гортани)", r"отек\w* (горла|языка|гортани)",
    r"отравил", r"хочу умереть", r"покончить с собой", r"суицид",
]
_emergency_re = re.compile("|".join(EMERGENCY_PATTERNS), re.IGNORECASE)

TRIAGE_PROMPT = (
    "Ты определяешь, описывает ли пациент ЭКСТРЕННОЕ, угрожающее жизни состояние, при котором нужно "
    "немедленно вызывать скорую: острая боль или давление в груди, признаки инсульта (перекос лица, "
    "онемение руки или ноги, нарушение речи, внезапная сильная головная боль), тяжёлое удушье, потеря "
    "сознания, судороги, сильное кровотечение, анафилаксия, отравление, суицидальные намерения. "
    "Обычные симптомы (насморк, больное горло, умеренная температура, лёгкая головная боль, кашель) "
    "НЕ являются экстренными. Ответь JSON: {\"emergency\": true} или {\"emergency\": false}."
)


class Text(BaseModel):
    text: str


def llm_is_emergency(text: str) -> bool:
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
    with urllib.request.urlopen(req, timeout=60) as resp:
        content = json.loads(resp.read().decode("utf-8"))["message"]["content"]
    return bool(json.loads(content).get("emergency"))


@app.post("/api/triage")
def triage(t: Text):
    """Экстренное ли состояние: правила + нейросеть. При недоступности модели работают только правила."""
    if _emergency_re.search(t.text):
        return {"emergency": True, "source": "rules"}
    try:
        if llm_is_emergency(t.text):
            return {"emergency": True, "source": "llm"}
    except Exception:
        pass
    return {"emergency": False}


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
    """Логирует подтверждённую жалобу в JSON и просит модель задать следующий уточняющий вопрос."""
    with _lock:
        items = _load()
        items.append({"n": len(items) + 1, "question": c.question, "complaint": c.text})
        _save(items)

    try:
        question = ask_model(items)
    except Exception as e:
        return {"count": len(items), "question": None, "error": f"Модель недоступна: {e}"}
    return {"count": len(items), "question": question}


FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
]


def build_protocol_pdf(items: list) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape

    regular, bold = "Helvetica", "Helvetica-Bold"
    for reg_path, bold_path in FONT_CANDIDATES:
        if os.path.exists(reg_path) and os.path.exists(bold_path):
            pdfmetrics.registerFont(TTFont("Proto", reg_path))
            pdfmetrics.registerFont(TTFont("Proto-Bold", bold_path))
            regular, bold = "Proto", "Proto-Bold"
            break

    title = ParagraphStyle("t", fontName=bold, fontSize=16, leading=22, spaceAfter=4)
    meta = ParagraphStyle("m", fontName=regular, fontSize=10, textColor="#5f6368", leading=14, spaceAfter=10)
    h = ParagraphStyle("h", fontName=bold, fontSize=12, leading=16, spaceBefore=10, spaceAfter=4)
    q = ParagraphStyle("q", fontName=regular, fontSize=10, leading=14, textColor="#5f6368", spaceBefore=6)
    a = ParagraphStyle("a", fontName=regular, fontSize=11, leading=15, leftIndent=8)

    story = [
        Paragraph("Направление к врачу-терапевту", title),
        Paragraph(f"Предварительный протокол сбора анамнеза · {datetime.now():%d.%m.%Y %H:%M}", meta),
        Paragraph("Жалобы и анамнез со слов пациента", h),
    ]
    if not items:
        story.append(Paragraph("Жалобы не зафиксированы.", a))
    for it in items:
        if it.get("question"):
            story.append(Paragraph("Вопрос ИИ: " + escape(it["question"]), q))
        story.append(Paragraph("• " + escape(it["complaint"]), a))
    story += [Spacer(1, 10 * mm), Paragraph(
        "Документ сформирован автоматически ИИ-помощником на основе ответов пациента и не является медицинским заключением.",
        meta)]

    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                      topMargin=20 * mm, bottomMargin=20 * mm, title="Протокол анамнеза").build(story)
    return buf.getvalue()


@app.get("/api/protocol.pdf")
def protocol_pdf():
    with _lock:
        items = _load()
    return Response(
        build_protocol_pdf(items),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="protocol.pdf"'},
    )
