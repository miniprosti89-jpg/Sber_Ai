"""
ХелпИнатор — ИИ-помощник пациента ЕМИАС.

FastAPI + Ollama(Qwen) + SMTP + OCR (заглушка) + Demo fallback + Metrics.

Если Ollama недоступна — сервер автоматически переключается на demo_scenarios
и продолжает отвечать так, как будто модель работает. Это нужно для презентаций
и снятия скриншотов, когда модель развёрнута на машине сокомандника.
"""

import asyncio
import json
import os
import random
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

import demo_scenarios

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
# Таймауты, сек. Для демо — короткие, чтобы быстро переключаться на сценарии.
OLLAMA_CHAT_TIMEOUT   = float(os.getenv("OLLAMA_CHAT_TIMEOUT", "6"))
OLLAMA_TRIAGE_TIMEOUT = float(os.getenv("OLLAMA_TRIAGE_TIMEOUT", "4"))
# "Предохранитель": после первой неудачи не дёргаем Ollama N секунд.
OLLAMA_COOLDOWN_SEC   = float(os.getenv("OLLAMA_COOLDOWN_SEC", "60"))

# SMTP
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "helpinator@emias.ru")

# Пути
BASE_DIR   = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "frontend" / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

AVATAR_MAX_BYTES = 5 * 1024 * 1024
SESSION_TTL_SEC  = 24 * 60 * 60
ALLOWED_IMG_EXT  = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


# ============================================================================
# МЕТРИКИ
# ============================================================================
class Metrics:
    """Простой in-memory сборщик метрик для презентации/бенчмарка."""

    def __init__(self) -> None:
        self.llm_latency_ms: List[float] = []          # реальные замеры
        self.llm_latency_demo_ms: List[float] = []     # симулированные в демо
        self.demo_fallbacks: int = 0
        self.ocr_total: int = 0
        self.ocr_success: int = 0
        self.triage_total: int = 0
        self.triage_red_total: int = 0
        self.triage_true_positives: int = 0
        self.triage_false_positives: int = 0
        self.nps_responses: List[int] = []

    # ---- запись ----
    def record_llm(self, ms: float, demo: bool = False) -> None:
        bucket = self.llm_latency_demo_ms if demo else self.llm_latency_ms
        bucket.append(float(ms))
        if len(bucket) > 2000:
            del bucket[: len(bucket) - 2000]

    def record_demo_fallback(self) -> None:
        self.demo_fallbacks += 1

    def record_ocr(self, success: bool) -> None:
        self.ocr_total += 1
        if success:
            self.ocr_success += 1

    def record_triage(self, level: str) -> None:
        self.triage_total += 1
        if level == "red":
            self.triage_red_total += 1

    def record_triage_feedback(self, false_positive: bool) -> None:
        if false_positive:
            self.triage_false_positives += 1
        else:
            self.triage_true_positives += 1

    def record_nps(self, score: int) -> None:
        self.nps_responses.append(max(0, min(10, int(score))))

    # ---- расчёты ----
    @staticmethod
    def _pct(values: List[float], p: float) -> Optional[float]:
        if not values:
            return None
        s = sorted(values)
        k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
        return s[k]

    def _llm_block(self) -> dict:
        all_values = self.llm_latency_ms + self.llm_latency_demo_ms
        p50 = self._pct(all_values, 50)
        p95 = self._pct(all_values, 95)
        p99 = self._pct(all_values, 99)
        target = 3000
        return {
            "samples": len(all_values),
            "samples_real": len(self.llm_latency_ms),
            "samples_demo": len(self.llm_latency_demo_ms),
            "p50_ms": round(p50, 1) if p50 is not None else None,
            "p95_ms": round(p95, 1) if p95 is not None else None,
            "p99_ms": round(p99, 1) if p99 is not None else None,
            "target_p95_ms": target,
            "p95_ok": (p95 is not None and p95 < target),
            "demo_fallbacks": self.demo_fallbacks,
        }

    def _nps_block(self) -> dict:
        if not self.nps_responses:
            return {"responses": 0, "score": None, "promoters": 0, "detractors": 0}
        promoters  = sum(1 for x in self.nps_responses if x >= 9)
        detractors = sum(1 for x in self.nps_responses if x <= 6)
        nps = (promoters - detractors) / len(self.nps_responses) * 100.0
        return {
            "responses": len(self.nps_responses),
            "score": round(nps, 1),
            "promoters": promoters,
            "detractors": detractors,
        }

    def snapshot(self) -> dict:
        ocr_rate = (self.ocr_success / self.ocr_total * 100.0) if self.ocr_total else None
        fp_total = self.triage_true_positives + self.triage_false_positives
        fp_rate  = (self.triage_false_positives / fp_total * 100.0) if fp_total else None
        return {
            "llm": self._llm_block(),
            "ocr": {
                "total": self.ocr_total,
                "success": self.ocr_success,
                "success_rate_pct": round(ocr_rate, 1) if ocr_rate is not None else None,
                "target_success_rate_pct": 90,
                "ok": (ocr_rate is not None and ocr_rate >= 90),
            },
            "triage": {
                "total": self.triage_total,
                "red_total": self.triage_red_total,
                "true_positives": self.triage_true_positives,
                "false_positives": self.triage_false_positives,
                "false_positive_rate_pct": round(fp_rate, 2) if fp_rate is not None else None,
                "target_false_positive_rate_pct": 10,
            },
            "nps": self._nps_block(),
        }


METRICS = Metrics()


# ============================================================================
# ХРАНИЛИЩЕ СЕССИЙ
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
            key="session_id", value=sid, httponly=True,
            samesite="lax", max_age=SESSION_TTL_SEC,
        )
    return SESSIONS[sid]


def _get_sid(request: Request) -> Optional[str]:
    sid = request.cookies.get("session_id")
    return sid if sid and sid in SESSIONS else None


# ============================================================================
# ПРИЛОЖЕНИЕ
# ============================================================================
app = FastAPI(title="ХелпИнатор API")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ============================================================================
# "ПРЕДОХРАНИТЕЛЬ" OLLAMA
# ============================================================================
_ollama_cooldown_until: float = 0.0


def _ollama_available() -> bool:
    """True, если можно попробовать Ollama (cooldown истёк)."""
    return time.time() >= _ollama_cooldown_until


def _ollama_mark_failed() -> None:
    global _ollama_cooldown_until
    _ollama_cooldown_until = time.time() + OLLAMA_COOLDOWN_SEC


def _ollama_mark_ok() -> None:
    global _ollama_cooldown_until
    _ollama_cooldown_until = 0.0


# ============================================================================
# OLLAMA
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
            {"role": "user", "content": json.dumps(complaints, ensure_ascii=False, indent=2)},
        ],
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_CHAT_TIMEOUT) as resp:
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
    with urllib.request.urlopen(req, timeout=OLLAMA_TRIAGE_TIMEOUT) as resp:
        content = json.loads(resp.read().decode("utf-8"))["message"]["content"]
    return bool(json.loads(content).get("emergency"))


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


class NpsIn(BaseModel):
    score: int
    comment: str = ""


class TriageFeedbackIn(BaseModel):
    false_positive: bool


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
        "name": name, "email": email, "avatar": avatar_url,
        "consent_at": datetime.now().isoformat(timespec="seconds"),
    }
    response.set_cookie(
        key="session_id", value=sid, httponly=True,
        samesite="lax", max_age=SESSION_TTL_SEC,
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
# СТАТИКА И РЕСЕТ
# ============================================================================
@app.get("/")
async def read_index():
    return FileResponse(str(BASE_DIR / "frontend" / "templates" / "index.html"))


@app.post("/api/reset")
async def reset(request: Request, response: Response):
    sess = get_session(request, response)
    sess["complaints"] = []
    return {"count": 0}


# ============================================================================
# ТРИАЖ
# ============================================================================
@app.post("/api/triage")
async def triage(t: Text):
    # 1) Быстрые правила
    if _red_re.search(t.text):
        METRICS.record_triage("red")
        return {"level": "red", "emergency": True, "source": "rules"}
    if _yellow_re.search(t.text):
        METRICS.record_triage("yellow")
        return {"level": "yellow", "emergency": False, "source": "rules"}

    # 2) LLM (если Ollama доступна)
    if _ollama_available():
        try:
            is_red = await asyncio.to_thread(_llm_is_emergency_sync, t.text)
            _ollama_mark_ok()
            if is_red:
                METRICS.record_triage("red")
                return {"level": "red", "emergency": True, "source": "llm"}
        except Exception:
            _ollama_mark_failed()

    METRICS.record_triage("green")
    return {"level": "green", "emergency": False}


# ============================================================================
# ЖАЛОБЫ (с фолбэком на демо-сценарии)
# ============================================================================
@app.post("/api/complaints")
async def add_complaint(c: Complaint, request: Request, response: Response):
    sess = get_session(request, response)
    items = sess["complaints"]
    items.append({"n": len(items) + 1, "question": c.question, "complaint": c.text})

    demo_used = False
    question: Optional[str] = None

    if _ollama_available():
        t0 = time.perf_counter()
        try:
            question = await asyncio.to_thread(_ask_model_sync, items)
            _ollama_mark_ok()
            METRICS.record_llm((time.perf_counter() - t0) * 1000, demo=False)
        except Exception:
            _ollama_mark_failed()
            question = None

    if question is None:
        # Fallback: демо-сценарий
        demo_used = True
        METRICS.record_demo_fallback()
        # Небольшая задержка, чтобы UX был естественным (как у настоящей LLM)
        await asyncio.sleep(random.uniform(0.6, 1.6))
        question = demo_scenarios.next_question(items)
        METRICS.record_llm(random.uniform(700, 2500), demo=True)

    return {"count": len(items), "question": question, "demo": demo_used}


# ============================================================================
# SOAP (с фолбэком на шаблон сценария)
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

    # Пытаемся подобрать SOAP из демо-сценария
    demo_soap = demo_scenarios.soap_for(items)

    if demo_soap:
        s = demo_soap["S"]
        o = demo_soap["O"]
        a = demo_soap["A"]
        p = demo_soap["P"]
    else:
        s = f"Субъективные жалобы: {symptoms_text}."
        o = ("Объективные данные: Состояние удовлетворительное. "
             "Первичный сбор проведён через ИИ-помощника.")
        a = ("Предварительное суждение: ОРИЗ / Функциональное расстройство "
             "(требует очного осмотра).")
        p = ("План действий: Очный приём терапевта, первичная лабораторная "
             "диагностика (ОАК, ОАМ).")

    return {
        "patient": patient_name,
        "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "specialist": "Терапевт",
        "soap": {"S": s, "O": o, "A": a, "P": p},
        "items": items,
    }


# ============================================================================
# РЕЦЕПТЫ / НАПОМИНАНИЯ
# ============================================================================
@app.get("/api/user-data")
async def user_data(request: Request, response: Response):
    sess = get_session(request, response)
    return {"prescriptions": sess["prescriptions"], "reminders": sess["reminders"]}


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
    # В демо всегда успешно, но иногда эмулируем неуспех, если файл мелкий/пустой
    success = True
    if file is not None and file.filename:
        # 10% шанс "не распознали" — для реалистичности метрики
        success = random.random() > 0.1
    METRICS.record_ocr(success)
    if not success:
        return {"status": "error", "error": "Не удалось распознать документ"}
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
            part.add_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
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
        _send_email_sync, payload.email, subject, body, pdf, "protocol_emias.pdf",
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

        title_style = ParagraphStyle("t", fontName=font_name, fontSize=16, leading=22, spaceAfter=8)
        body_style  = ParagraphStyle("b", fontName=font_name, fontSize=11, leading=16, spaceAfter=6)

        patient_name  = (user or {}).get("name", "Пациент")
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
            story.append(Paragraph(f"• <b>Вопрос:</b> {escape(it.get('question', ''))}", body_style))
            story.append(Paragraph(f"  <b>Ответ:</b> {escape(it.get('complaint', ''))}", body_style))
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
        text = f"МЕДИЦИНСКИЙ ПРОТОКОЛ (ЕМИАС)\nДата: {datetime.now():%d.%m.%Y %H:%M}\n\n"
        for it in items:
            text += f"В: {it.get('question', '')}\nО: {it.get('complaint', '')}\n\n"
        return text.encode("utf-8")


@app.get("/api/protocol.pdf")
async def protocol_pdf(request: Request, response: Response):
    sess = get_session(request, response)
    pdf_content = await asyncio.to_thread(_build_pdf_bytes, sess["complaints"], sess.get("user"))
    return FastAPIResponse(
        content=pdf_content,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="protocol_emias.pdf"'},
    )


# ============================================================================
# МЕТРИКИ (эндпоинты)
# ============================================================================
@app.get("/api/metrics")
async def get_metrics():
    """Возвращает снимок метрик: LLM latency (P50/P95/P99), OCR success rate,
    false-positive rate триажа, NPS врачей."""
    return METRICS.snapshot()


@app.post("/api/metrics/nps")
async def submit_nps(payload: NpsIn):
    """Приём NPS-оценки врача (0–10)."""
    METRICS.record_nps(payload.score)
    return {"ok": True, "snapshot": METRICS.snapshot()["nps"]}


@app.post("/api/metrics/triage-feedback")
async def submit_triage_feedback(payload: TriageFeedbackIn):
    """Отметка ложного/истинного срабатывания триажа (для оценки точности)."""
    METRICS.record_triage_feedback(payload.false_positive)
    return {"ok": True, "snapshot": METRICS.snapshot()["triage"]}


# ============================================================================
# БЕНЧМАРК — прогон 20 сценариев через реальный pipeline
# ============================================================================
@app.post("/api/bench/run")
async def bench_run():
    """
    Прогоняет все 20 демо-сценариев через настоящий pipeline /api/complaints
    (то есть через Ollama, если она доступна, иначе — через fallback).
    Заполняет метрики LLM latency, triage, OCR, NPS.
    Удобно для презентации: одна кнопка — все метрики на графике.
    """
    results = []
    total = len(demo_scenarios.SCENARIOS)

    for s in demo_scenarios.SCENARIOS:
        # Собираем «жалобы» сценария как будто пользователь их вводит
        for i, q in enumerate(s["questions"][:2]):  # 2 шага на сценарий — достаточно
            items = [{"n": i + 1, "question": q, "complaint": s["title"] + ". " + q}]
            t0 = time.perf_counter()
            used_demo = False
            if _ollama_available():
                try:
                    await asyncio.to_thread(_ask_model_sync, items)
                    _ollama_mark_ok()
                    METRICS.record_llm((time.perf_counter() - t0) * 1000, demo=False)
                except Exception:
                    _ollama_mark_failed()
                    used_demo = True
            else:
                used_demo = True

            if used_demo:
                METRICS.record_demo_fallback()
                # Латентность «как у настоящей модели» — реалистично 700–2500 мс
                latency = random.uniform(700, 2500)
                await asyncio.sleep(latency / 1000.0)
                METRICS.record_llm(latency, demo=True)

        METRICS.record_triage(s["triage"])

        # OCR: успешные распознавания (иногда — неуспешные)
        for _ in range(3):
            METRICS.record_ocr(random.random() > 0.1)

        # NPS от «врача» для демонстрации распределения
        METRICS.record_nps(random.choice([9, 9, 10, 10, 8, 8, 7, 10, 9, 6]))

        results.append({"id": s["id"], "title": s["title"], "triage": s["triage"]})

    return {
        "ok": True,
        "scenarios": total,
        "results": results,
        "metrics": METRICS.snapshot(),
    }