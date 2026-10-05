"""
ХелпИнатор — ИИ-помощник пациента ЕМИАС.
FastAPI + Ollama + SMTP + OCR (заглушка).

ВАЖНО: для работы multipart-форм (/api/login) требуется пакет
       `python-multipart`. Он указан в requirements.txt.
"""

import asyncio
import json
import os
import re
import smtplib
import time
import uuid
import urllib.request
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI, Response, Request, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "helpinator@emias.ru")

BASE_DIR   = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "frontend" / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

AVATAR_MAX_BYTES = 5 * 1024 * 1024         # 5 МБ на аватар
SESSION_TTL_SEC  = 24 * 60 * 60            # сутки
ALLOWED_IMG_EXT  = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}

# ============================================================================
# ПРИЛОЖЕНИЕ
# ============================================================================
app = FastAPI(title="ХелпИнатор API")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ============================================================================
# ХРАНИЛИЩЕ СЕССИЙ (в памяти)
# SESSIONS[sid] = {
#     "user":          {"name", "email", "avatar", "consent_at"},
#     "complaints":    [{"n", "question", "complaint"}],
#     "prescriptions": [{"id", "name", "dosage", "schedule"}],
#     "reminders":     [{"id", "med", "time", "note"}],
#     "created":       float,
#     "touched":       float,
# }
# ============================================================================
SESSIONS: Dict[str, dict] = {}


def _new_session() -> dict:
    now = time.time()
    return {
        "user": None,
        "complaints": [],
        "prescriptions": [],
        "reminders": [],
        "created": now,
        "touched": now,
    }


def _gc_sessions() -> None:
    """Удаляет сессии старше SESSION_TTL_SEC."""
    cutoff = time.time() - SESSION_TTL_SEC
    for sid in [s for s, v in SESSIONS.items() if v.get("touched", 0) < cutoff]:
        SESSIONS.pop(sid, None)


def _touch(sess: dict) -> None:
    sess["touched"] = time.time()


def get_session(
    request: Request,
    response: Optional[Response] = None,
    create: bool = True,
) -> Optional[dict]:
    _gc_sessions()
    sid = request.cookies.get("session_id")
    if sid and sid in SESSIONS:
        sess = SESSIONS[sid]
        _touch(sess)
        return sess

    if not create:
        return None

    sid = str(uuid.uuid4())
    SESSIONS[sid] = _new_session()
    if response is not None:
        response.set_cookie(
            key="session_id",
            value=sid,
            httponly=True,
            samesite="lax",
            max_age=SESSION_TTL_SEC,
        )
    return SESSIONS[sid]


def _get_sid(request: Request) -> Optional[str]:
    sid = request.cookies.get("session_id")
    return sid if sid and sid in SESSIONS else None


# ============================================================================
# МОДЕЛИ
# ============================================================================
class Text(BaseModel):
    text: str


class Complaint(BaseModel):
    text: str
    question: str = ""


class PrescriptionIn(BaseModel):
    name: str
    dosage: str = ""
    schedule: str = ""


class ReminderIn(BaseModel):
    med: str
    time: str
    note: str = ""


class EmailIn(BaseModel):
    email: str


# ============================================================================
# АВТОРИЗАЦИЯ
# ============================================================================
@app.post("/api/login")
async def login(
    request: Request,
    response: Response,
    name: str = Form(...),
    email: str = Form(...),
    consent: bool = Form(...),
    avatar: Optional[UploadFile] = File(None),
):
    if not consent:
        return JSONResponse(
            {"error": "Необходимо согласие на обработку данных (152-ФЗ)."},
            status_code=400,
        )

    name = (name or "").strip()
    email = (email or "").strip()
    if not name or not email or "@" not in email:
        return JSONResponse(
            {"error": "Заполните корректно имя и email."},
            status_code=400,
        )

    sid = str(uuid.uuid4())
    avatar_url = "/static/img/default_avatar.svg"

    if avatar is not None and avatar.filename:
        content = await avatar.read()
        if content:
            if len(content) > AVATAR_MAX_BYTES:
                return JSONResponse(
                    {"error": "Аватар слишком большой (макс. 5 МБ)."},
                    status_code=413,
                )
            ext = Path(avatar.filename).suffix.lower()
            if ext not in ALLOWED_IMG_EXT:
                ext = ".png"
            fname = f"{sid[:8]}_{uuid.uuid4().hex[:8]}{ext}"
            (UPLOAD_DIR / fname).write_bytes(content)
            avatar_url = f"/static/uploads/{fname}"

    SESSIONS[sid] = _new_session()
    SESSIONS[sid]["user"] = {
        "name": name,
        "email": email,
        "avatar": avatar_url,
        "consent_at": datetime.now().isoformat(timespec="seconds"),
    }
    response.set_cookie(
        key="session_id",
        value=sid,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL_SEC,
    )
    return {"ok": True, "user": SESSIONS[sid]["user"]}


@app.get("/api/me")
async def me(request: Request):
    sid = _get_sid(request)
    if not sid or not SESSIONS[sid].get("user"):
        return JSONResponse({"error": "not_authenticated"}, status_code=401)
    return {"user": SESSIONS[sid]["user"]}


@app.post("/api/logout")
async def logout(request: Request, response: Response):
    sid = _get_sid(request)
    if sid:
        SESSIONS.pop(sid, None)
    response.delete_cookie("session_id")
    return {"ok": True}


# ============================================================================
# OLLAMA (уточняющий вопрос + триаж)
# ============================================================================
def _ask_model_sync(complaints: list) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты медицинский ИИ-помощник, собирающий анамнез перед приёмом "
                    "у терапевта. Тебе дают JSON со всеми жалобами пациента. "
                    "Придумай ОДИН следующий вопрос пациенту, который поможет "
                    "уточнить его состояние (длительность, интенсивность, "
                    "сопутствующие симптомы, принимаемые лекарства и т.п.). "
                    "Не повторяй уже заданные вопросы. Не ставь диагнозов. "
                    "Отвечай по-русски, только текстом вопроса, без пояснений."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(complaints, ensure_ascii=False, indent=2),
            },
        ],
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))["message"]["content"].strip()


RED_PATTERNS = [
    r"боль\w* (в|за) (груди|грудин)", r"давит (в|за) (груди|грудин)",
    r"сердечн\w+ приступ", r"инфаркт", r"инсульт",
    r"перекосил[оа]? (лицо|рот)",
    r"(онемел|отнял)\w* (рука|нога|половина|лицо|лиц)",
    r"не могу (говорить|дышать|вдохнуть)", r"задыха\w+",
    r"нечем дышать", r"удуш",
    r"потерял\w* сознание", r"без сознания", r"обморок", r"судорог",
    r"сильн\w+ кровотечени", r"кровь не останавливается",
    r"кашляю кровью", r"рвота кровью",
    r"анафилакт", r"отёк\w* (горла|языка|гортани)", r"отек\w* (горла|языка|гортани)",
    r"отравил", r"хочу умереть", r"покончить с собой", r"суицид",
]
_red_re = re.compile("|".join(RED_PATTERNS), re.IGNORECASE)

YELLOW_PATTERNS = [
    r"высокая температура", r"39\b", r"40\b",
    r"сильная боль в животе", r"острая боль",
    r"рвота", r"высокое давление", r"гипертонич", r"головокружен",
]
_yellow_re = re.compile("|".join(YELLOW_PATTERNS), re.IGNORECASE)

TRIAGE_PROMPT = (
    "Ты определяешь, описывает ли пациент ЭКСТРЕННОЕ, угрожающее жизни "
    "состояние. Ответь JSON: {\"emergency\": true} или {\"emergency\": false}."
)


def _llm_is_emergency_sync(text: str) -> bool:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": {
            "type": "object",
            "properties": {"emergency": {"type": "boolean"}},
            "required": ["emergency"],
        },
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": TRIAGE_PROMPT},
            {"role": "user", "content": text},
        ],
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        content = json.loads(resp.read().decode("utf-8"))["message"]["content"]
    return bool(json.loads(content).get("emergency"))


# ============================================================================
# ТРИАЖ
# ============================================================================
@app.post("/api/triage")
async def triage(t: Text):
    if _red_re.search(t.text):
        return {"level": "red", "emergency": True, "source": "rules"}
    if _yellow_re.search(t.text):
        return {"level": "yellow", "emergency": False, "source": "rules"}
    try:
        if await asyncio.to_thread(_llm_is_emergency_sync, t.text):
            return {"level": "red", "emergency": True, "source": "llm"}
    except Exception:
        pass
    return {"level": "green", "emergency": False}


# ============================================================================
# СТАТИКА И РЕСЕТ
# ============================================================================
@app.get("/")
async def read_index():
    index_path = BASE_DIR / "frontend" / "templates" / "index.html"
    return FileResponse(str(index_path))


@app.post("/api/reset")
async def reset(request: Request, response: Response):
    sess = get_session(request, response)
    sess["complaints"] = []
    return {"count": 0}


# ============================================================================
# ЖАЛОБЫ
# ============================================================================
@app.post("/api/complaints")
async def add_complaint(c: Complaint, request: Request, response: Response):
    sess = get_session(request, response)
    items = sess["complaints"]
    items.append(
        {"n": len(items) + 1, "question": c.question, "complaint": c.text}
    )
    try:
        question = await asyncio.to_thread(_ask_model_sync, items)
    except Exception as e:
        return {
            "count": len(items),
            "question": None,
            "error": f"Модель недоступна: {e}",
        }
    return {"count": len(items), "question": question}


# ============================================================================
# SOAP
# ============================================================================
@app.get("/api/soap")
async def get_soap_protocol(request: Request, response: Response):
    sess = get_session(request, response)
    items = sess["complaints"]
    user = sess.get("user") or {}
    patient_name = user.get("name", "Пациент")

    symptoms_text = (
        "; ".join(it["complaint"] for it in items)
        if items
        else "Жалобы не зафиксированы"
    )

    return {
        "patient": patient_name,
        "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "specialist": "Терапевт",
        "soap": {
            "S": f"Субъективные жалобы: {symptoms_text}.",
            "O": "Объективные данные: Состояние удовлетворительное. "
                 "Первичный сбор проведён через ИИ-помощника.",
            "A": "Предварительное суждение: ОРИЗ / Функциональное расстройство "
                 "(требует очного осмотра).",
            "P": "План действий: Очный приём терапевта, первичная лабораторная "
                 "диагностика (ОАК, ОАМ).",
        },
        "items": items,
    }


# ============================================================================
# РЕЦЕПТЫ И НАПОМИНАНИЯ
# ============================================================================
@app.get("/api/user-data")
async def user_data(request: Request, response: Response):
    sess = get_session(request, response)
    return {
        "prescriptions": sess["prescriptions"],
        "reminders": sess["reminders"],
    }


@app.post("/api/prescriptions")
async def add_prescription(p: PrescriptionIn, request: Request, response: Response):
    sess = get_session(request, response)
    sess["prescriptions"].append({
        "id": uuid.uuid4().hex,
        "name": p.name.strip(),
        "dosage": p.dosage.strip(),
        "schedule": p.schedule.strip(),
    })
    return {"ok": True, "prescriptions": sess["prescriptions"]}


@app.delete("/api/prescriptions/{pid}")
async def del_prescription(pid: str, request: Request, response: Response):
    sess = get_session(request, response)
    sess["prescriptions"] = [x for x in sess["prescriptions"] if x["id"] != pid]
    return {"ok": True, "prescriptions": sess["prescriptions"]}


@app.post("/api/reminders")
async def add_reminder(r: ReminderIn, request: Request, response: Response):
    sess = get_session(request, response)
    sess["reminders"].append({
        "id": uuid.uuid4().hex,
        "med": r.med.strip(),
        "time": r.time,
        "note": r.note.strip(),
    })
    return {"ok": True, "reminders": sess["reminders"]}


@app.delete("/api/reminders/{rid}")
async def del_reminder(rid: str, request: Request, response: Response):
    sess = get_session(request, response)
    sess["reminders"] = [x for x in sess["reminders"] if x["id"] != rid]
    return {"ok": True, "reminders": sess["reminders"]}


# ============================================================================
# OCR (заглушка)
# ============================================================================
@app.post("/api/ocr")
async def process_ocr(file: UploadFile = File(None)):
    await asyncio.sleep(1.0)
    return {
        "status": "success",
        "extracted_meds": [
            {"name": "Амоксиклав 500 мг", "schedule": "2 раза в день (после еды)"},
            {"name": "Витамин C 1000 мг", "schedule": "1 раз в день (утро)"},
        ],
    }


# ============================================================================
# EMAIL / SMTP
# ============================================================================
def _send_email_sync(
    to_email: str,
    subject: str,
    body: str,
    attachment: Optional[bytes] = None,
    attachment_name: str = "protocol.pdf",
) -> Tuple[bool, str]:
    """
    Возвращает (ok, mode_or_error).
    Если SMTP не настроен — режим 'simulated'.
    """
    if not SMTP_HOST or not SMTP_USER:
        return True, "simulated"

    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        if attachment:
            part = MIMEApplication(attachment, _subtype="pdf")
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{attachment_name}"',
            )
            msg.attach(part)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        return True, "sent"
    except Exception as e:
        return False, str(e)


@app.post("/api/send-protocol")
async def send_protocol(payload: EmailIn, request: Request, response: Response):
    sess = get_session(request, response)
    user = sess.get("user") or {}

    pdf = await asyncio.to_thread(_build_pdf_bytes, sess["complaints"], user)

    subject = f"Медицинский протокол пациента {user.get('name', '')}".strip()
    body = (
        "Уважаемый врач!\n\n"
        "Направляю протокол первичного анамнеза пациента.\n"
        f"Пациент: {user.get('name', '—')}\n"
        f"Обратный email пациента: {user.get('email', '—')}\n\n"
        "С уважением,\nИИ-помощник ХелпИнатор"
    )

    ok, info = await asyncio.to_thread(
        _send_email_sync, payload.email, subject, body, pdf, "protocol_emias.pdf"
    )
    if not ok:
        return JSONResponse({"error": info}, status_code=500)
    return {"ok": True, "mode": info, "to": payload.email}


# ============================================================================
# PDF
# ============================================================================
def _build_pdf_bytes(items: list, user: Optional[dict] = None) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
        from xml.sax.saxutils import escape

        font_name = "Helvetica"
        for reg_path in [
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/Library/Fonts/Arial.ttf",
        ]:
            if os.path.exists(reg_path):
                pdfmetrics.registerFont(TTFont("CustomFont", reg_path))
                font_name = "CustomFont"
                break

        title_style = ParagraphStyle(
            "t", fontName=font_name, fontSize=16, leading=22, spaceAfter=8,
        )
        body_style = ParagraphStyle(
            "b", fontName=font_name, fontSize=11, leading=16, spaceAfter=6,
        )

        patient_name = (user or {}).get("name", "Пациент")
        patient_email = (user or {}).get("email", "—")

        story = [
            Paragraph("<b>МЕДИЦИНСКИЙ ПРОТОКОЛ (ЕМИАС)</b>", title_style),
            Paragraph(f"Дата формирования: {datetime.now():%d.%m.%Y %H:%M}", body_style),
            Paragraph(f"<b>Пациент:</b> {escape(patient_name)}", body_style),
            Paragraph(f"<b>Email пациента:</b> {escape(patient_email)}", body_style),
            Spacer(1, 8 * mm),
            Paragraph("<b>Собранный анамнез:</b>", body_style),
        ]
        for it in items:
            story.append(Paragraph(
                f"• <b>Вопрос:</b> {escape(it.get('question', ''))}", body_style,
            ))
            story.append(Paragraph(
                f"  <b>Ответ:</b> {escape(it.get('complaint', ''))}", body_style,
            ))
            story.append(Spacer(1, 3 * mm))

        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=20 * mm, rightMargin=20 * mm,
            topMargin=20 * mm, bottomMargin=20 * mm,
        )
        doc.build(story)
        return buf.getvalue()
    except Exception:
        # Простой текстовый фоллбэк
        text = (
            f"МЕДИЦИНСКИЙ ПРОТОКОЛ (ЕМИАС)\n"
            f"Дата: {datetime.now():%d.%m.%Y %H:%M}\n\n"
        )
        for it in items:
            text += f"В: {it.get('question', '')}\nО: {it.get('complaint', '')}\n\n"
        return text.encode("utf-8")


@app.get("/api/protocol.pdf")
async def protocol_pdf(request: Request, response: Response):
    sess = get_session(request, response)
    pdf_content = await asyncio.to_thread(
        _build_pdf_bytes, sess["complaints"], sess.get("user"),
    )
    return FastAPIResponse(
        content=pdf_content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="protocol_emias.pdf"',
        },
    )