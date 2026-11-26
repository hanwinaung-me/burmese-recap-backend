from __future__ import annotations

import hmac
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

import jwt
import requests
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

APP_NAME = "Burmese Recap Studio API"
VERSION = "1.0.0"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
JWT_SECRET = os.getenv("JWT_SECRET", "")
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "")
TOKEN_EXPIRE_DAYS = int(os.getenv("TOKEN_EXPIRE_DAYS", "14"))

app = FastAPI(title=APP_NAME, version=VERSION, description="Single-owner API for Burmese Recap Studio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Worker-Token"],
)

bearer = HTTPBearer(auto_error=False)
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
DRIVE_ID_RE = re.compile(r"[-\w]{20,}")


def require_config() -> None:
    missing = [
        name for name, value in [
            ("SUPABASE_URL", SUPABASE_URL),
            ("SUPABASE_SECRET_KEY", SUPABASE_SECRET_KEY),
            ("APP_PASSWORD", APP_PASSWORD),
            ("JWT_SECRET", JWT_SECRET),
            ("WORKER_TOKEN", WORKER_TOKEN),
        ] if not value
    ]
    if missing:
        raise HTTPException(status_code=503, detail="Server setup is incomplete. Missing: " + ", ".join(missing))


def db_request(method: str, path: str, *, params: dict | None = None, body: Any = None) -> Any:
    require_config()
    url = f"{SUPABASE_URL}/rest/v1/{path.lstrip('/')}"
    headers = {
        "apikey": SUPABASE_SECRET_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    # New Supabase sb_secret_* keys are opaque and must not be sent as Bearer JWTs.
    # Legacy service_role keys are JWTs and still need the Authorization header.
    if not SUPABASE_SECRET_KEY.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {SUPABASE_SECRET_KEY}"
    if method.upper() in {"POST", "PATCH", "DELETE"}:
        headers["Prefer"] = "return=representation"
    try:
        response = requests.request(method, url, headers=headers, params=params, json=body, timeout=25)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail=f"Database connection failed: {exc.__class__.__name__}") from exc
    if response.status_code >= 400:
        detail = "Database request failed"
        try:
            data = response.json()
            detail = data.get("message") or data.get("details") or data.get("hint") or detail
        except ValueError:
            pass
        raise HTTPException(status_code=503, detail=detail)
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    require_config()
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Please sign in")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again") from exc
    if payload.get("sub") != "owner":
        raise HTTPException(status_code=401, detail="Invalid session")
    return payload


def check_worker(x_worker_token: str | None = Header(default=None)) -> None:
    require_config()
    if not x_worker_token or not hmac.compare_digest(x_worker_token, WORKER_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid worker token")


def extract_drive_id(value: str) -> str:
    value = value.strip()
    match = DRIVE_ID_RE.search(value)
    if not match:
        raise ValueError("Google Drive link/File ID မမှန်ပါ။ Drive link အပြည့် သို့မဟုတ် File ID ထည့်ပါ။")
    return match.group(0)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class JobCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_drive_file_id: str = Field(min_length=20, max_length=300)
    source_filename: str = Field(min_length=1, max_length=200)
    movie_title: str = Field(default="", max_length=200)
    target_minutes: int = Field(default=12, ge=5, le=30)
    channel_name: str = Field(min_length=1, max_length=80)
    watermark_enabled: bool = True
    watermark_opacity: int = Field(default=65, ge=10, le=100)
    subtitle_color: str = "#FFFFFF"
    subtitle_outline_color: str = "#000000"
    subtitle_font_size: int = Field(default=48, ge=28, le=80)
    subtitle_position: Literal["bottom", "top", "middle"] = "bottom"
    voice: str = Field(default="Charon", min_length=2, max_length=40)
    bgm_drive_file_id: str | None = Field(default=None, max_length=300)
    rights_confirmed: bool = False

    @field_validator("source_drive_file_id")
    @classmethod
    def clean_source_id(cls, value: str) -> str:
        return extract_drive_id(value)

    @field_validator("bgm_drive_file_id")
    @classmethod
    def clean_bgm_id(cls, value: str | None) -> str | None:
        if value:
            return extract_drive_id(value)
        return None

    @field_validator("subtitle_color", "subtitle_outline_color")
    @classmethod
    def check_hex_color(cls, value: str) -> str:
        if not HEX_COLOR.match(value):
            raise ValueError("အရောင်ကို #RRGGBB ပုံစံနဲ့ ရွေးပါ။")
        return value.upper()

    @field_validator("rights_confirmed")
    @classmethod
    def require_rights(cls, value: bool) -> bool:
        if not value:
            raise ValueError("ကိုယ်ပိုင်/လိုင်စင်ရ/အသုံးပြုခွင့်ရှိသော Video ဖြစ်ကြောင်း အတည်ပြုရပါမယ်။")
        return value


class ScriptUpdate(BaseModel):
    script_text: str = Field(min_length=50, max_length=100000)


class SettingsUpdate(BaseModel):
    subtitle_color: str | None = None
    subtitle_outline_color: str | None = None
    subtitle_font_size: int | None = Field(default=None, ge=28, le=80)
    subtitle_position: Literal["bottom", "top", "middle"] | None = None
    watermark_enabled: bool | None = None
    watermark_opacity: int | None = Field(default=None, ge=10, le=100)
    channel_name: str | None = Field(default=None, min_length=1, max_length=80)
    voice: str | None = Field(default=None, min_length=2, max_length=40)

    @field_validator("subtitle_color", "subtitle_outline_color")
    @classmethod
    def check_optional_color(cls, value: str | None) -> str | None:
        if value is not None and not HEX_COLOR.match(value):
            raise ValueError("အရောင်ကို #RRGGBB ပုံစံနဲ့ ရွေးပါ။")
        return value.upper() if value else value


class HighlightItem(BaseModel):
    start_seconds: float = Field(ge=0, le=200000)
    end_seconds: float = Field(gt=0, le=200000)
    reason: str = Field(default="", max_length=250)

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Scene အဆုံးချိန်သည် စတင်ချိန်ထက် နောက်ကျရပါမယ်။")
        if self.end_seconds - self.start_seconds > 180:
            raise ValueError("Scene တစ်ခုကို အများဆုံး ၁၈၀ စက္ကန့်သာ သတ်မှတ်နိုင်ပါတယ်။")
        return self


class HighlightUpdate(BaseModel):
    highlights_json: list[HighlightItem] = Field(max_length=250)


class WorkerProgress(BaseModel):
    progress: int = Field(ge=0, le=99)
    stage: str = Field(min_length=1, max_length=50)
    message: str = Field(default="", max_length=500)


class AnalysisChunk(BaseModel):
    chunk_index: int = Field(ge=0)
    chunk_data: dict
    progress: int = Field(ge=1, le=49)
    message: str = Field(default="", max_length=500)


class ScriptReady(BaseModel):
    script_text: str = Field(min_length=50, max_length=100000)
    analysis_json: dict
    highlights_json: list[dict]


class WorkerComplete(BaseModel):
    result_drive_file_id: str = Field(min_length=20, max_length=300)
    result_filename: str = Field(min_length=1, max_length=200)


class WorkerFailure(BaseModel):
    error_message: str = Field(min_length=1, max_length=2000)


def get_job(job_id: str) -> dict:
    try:
        UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    rows = db_request("GET", "recap_jobs", params={"id": f"eq.{job_id}", "select": "*", "limit": "1"})
    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")
    return rows[0]


def public_job(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "source_filename": row.get("source_filename"),
        "movie_title": row.get("movie_title"),
        "status": row.get("status"),
        "progress": row.get("progress", 0),
        "stage": row.get("stage", "queued"),
        "message": row.get("message", ""),
        "settings": row.get("settings") or {},
        "script_text": row.get("script_text") or "",
        "highlights_json": row.get("highlights_json") or [],
        "result_filename": row.get("result_filename"),
        "result_drive_file_id": row.get("result_drive_file_id"),
        "result_url": row.get("result_url"),
        "error_message": row.get("error_message"),
    }


@app.get("/")
def root():
    return {"app": APP_NAME, "version": VERSION, "status": "ok", "docs": "/docs"}


@app.get("/health")
def health():
    configured = bool(SUPABASE_URL and SUPABASE_SECRET_KEY and APP_PASSWORD and JWT_SECRET and WORKER_TOKEN)
    return {"status": "ok" if configured else "needs_setup", "app": APP_NAME, "version": VERSION, "database_configured": bool(SUPABASE_URL and SUPABASE_SECRET_KEY), "worker_configured": bool(WORKER_TOKEN)}


@app.post("/api/auth/login")
def login(payload: LoginRequest):
    require_config()
    if not hmac.compare_digest(payload.password, APP_PASSWORD):
        raise HTTPException(status_code=401, detail="Password မမှန်ပါ")
    expires = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    token = jwt.encode({"sub": "owner", "iat": datetime.now(timezone.utc), "exp": expires}, JWT_SECRET, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_in_days": TOKEN_EXPIRE_DAYS}


@app.get("/api/me")
def me(_: dict = Depends(current_user)):
    return {"user": "owner", "app": APP_NAME}


@app.post("/api/jobs")
def create_job(payload: JobCreate, _: dict = Depends(current_user)):
    settings = {
        "target_minutes": payload.target_minutes,
        "channel_name": payload.channel_name,
        "watermark_enabled": payload.watermark_enabled,
        "watermark_opacity": payload.watermark_opacity,
        "subtitle_color": payload.subtitle_color,
        "subtitle_outline_color": payload.subtitle_outline_color,
        "subtitle_font_size": payload.subtitle_font_size,
        "subtitle_position": payload.subtitle_position,
        "voice": payload.voice,
        "bgm_drive_file_id": payload.bgm_drive_file_id,
        "rights_confirmed": payload.rights_confirmed,
    }
    body = {
        "source_drive_file_id": payload.source_drive_file_id,
        "source_filename": payload.source_filename,
        "movie_title": payload.movie_title,
        "status": "queued",
        "progress": 0,
        "stage": "queued",
        "message": "အလုပ်စာရင်းထဲ ထည့်ပြီးပါပြီ။ Colab Worker က စတင်လုပ်ဆောင်မယ်။",
        "settings": settings,
        "analysis_json": {"chunks": []},
        "highlights_json": [],
        "script_text": None,
    }
    rows = db_request("POST", "recap_jobs", body=body)
    return public_job(rows[0])


@app.get("/api/jobs")
def list_jobs(_: dict = Depends(current_user)):
    rows = db_request("GET", "recap_jobs", params={"select": "*", "order": "created_at.desc", "limit": "50"})
    return {"jobs": [public_job(row) for row in (rows or [])]}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str, _: dict = Depends(current_user)):
    return public_job(get_job(job_id))


@app.patch("/api/jobs/{job_id}/script")
def update_script(job_id: str, payload: ScriptUpdate, _: dict = Depends(current_user)):
    row = get_job(job_id)
    if row.get("status") != "awaiting_approval":
        raise HTTPException(status_code=409, detail="Script ကို AI ရေးပြီး Review အဆင့်ရောက်မှ ပြင်နိုင်ပါတယ်။")
    rows = db_request("PATCH", "recap_jobs", params={"id": f"eq.{job_id}"}, body={"script_text": payload.script_text, "message": "မောင်ပြင်ထားတဲ့ Script ကို သိမ်းပြီးပါပြီ။"})
    return public_job(rows[0])


@app.patch("/api/jobs/{job_id}/settings")
def update_settings(job_id: str, payload: SettingsUpdate, _: dict = Depends(current_user)):
    row = get_job(job_id)
    if row.get("status") != "awaiting_approval":
        raise HTTPException(status_code=409, detail="Settings ကို Script Review အဆင့်မှာသာ ပြင်နိုင်ပါတယ်။")
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        return public_job(row)
    settings = dict(row.get("settings") or {})
    settings.update(changes)
    rows = db_request("PATCH", "recap_jobs", params={"id": f"eq.{job_id}"}, body={"settings": settings, "message": "Video Design Settings သိမ်းပြီးပါပြီ။"})
    return public_job(rows[0])


@app.patch("/api/jobs/{job_id}/highlights")
def update_highlights(job_id: str, payload: HighlightUpdate, _: dict = Depends(current_user)):
    row = get_job(job_id)
    if row.get("status") != "awaiting_approval":
        raise HTTPException(status_code=409, detail="Scene များကို Script Review အဆင့်မှာသာ ပြင်နိုင်ပါတယ်။")
    highlights = [item.model_dump() for item in payload.highlights_json]
    rows = db_request("PATCH", "recap_jobs", params={"id": f"eq.{job_id}"}, body={
        "highlights_json": highlights,
        "message": "ရွေးထားသော Scene များကို သိမ်းပြီးပါပြီ။",
    })
    return public_job(rows[0])


@app.post("/api/jobs/{job_id}/approve")
def approve_job(job_id: str, _: dict = Depends(current_user)):
    row = get_job(job_id)
    if row.get("status") != "awaiting_approval":
        raise HTTPException(status_code=409, detail="Approve လုပ်နိုင်တဲ့ Review အဆင့် မဟုတ်သေးပါ။")
    rows = db_request("PATCH", "recap_jobs", params={"id": f"eq.{job_id}"}, body={"status": "approved", "stage": "waiting_worker", "progress": 50, "message": "Script အတည်ပြုပြီးပါပြီ။ Worker က Voice နဲ့ Video ထုတ်မယ်။"})
    return public_job(rows[0])


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, _: dict = Depends(current_user)):
    row = get_job(job_id)
    if row.get("status") != "failed":
        raise HTTPException(status_code=409, detail="Failed ဖြစ်နေတဲ့ Job ကိုသာ ပြန်စနိုင်ပါတယ်။")
    next_status = "approved" if (row.get("script_text") or "").strip() else "queued"
    rows = db_request("PATCH", "recap_jobs", params={"id": f"eq.{job_id}"}, body={
        "status": next_status,
        "progress": 0 if next_status == "queued" else 50,
        "stage": "queued" if next_status == "queued" else "waiting_worker",
        "message": "Job ကို ပြန်စရန် စာရင်းထဲ ထည့်ပြီးပါပြီ။",
        "error_message": None,
    })
    return public_job(rows[0])


@app.post("/api/worker/claim")
def worker_claim(_: None = Depends(check_worker)):
    data = db_request("POST", "rpc/claim_recap_job", body={"p_worker_id": "colab-worker"})
    if not data:
        return {"job": None}
    row = data[0] if isinstance(data, list) else data
    return {"job": row}


@app.post("/api/worker/jobs/{job_id}/progress")
def worker_progress(job_id: str, payload: WorkerProgress, _: None = Depends(check_worker)):
    get_job(job_id)
    rows = db_request("PATCH", "recap_jobs", params={"id": f"eq.{job_id}"}, body={"progress": payload.progress, "stage": payload.stage, "message": payload.message})
    return {"ok": True, "job": public_job(rows[0])}


@app.post("/api/worker/jobs/{job_id}/analysis-chunk")
def worker_analysis_chunk(job_id: str, payload: AnalysisChunk, _: None = Depends(check_worker)):
    row = get_job(job_id)
    data = dict(row.get("analysis_json") or {"chunks": []})
    chunks = list(data.get("chunks") or [])
    by_index = {int(item.get("chunk_index", -1)): item for item in chunks if isinstance(item, dict)}
    by_index[payload.chunk_index] = {"chunk_index": payload.chunk_index, **payload.chunk_data}
    data["chunks"] = [by_index[index] for index in sorted(by_index)]
    rows = db_request("PATCH", "recap_jobs", params={"id": f"eq.{job_id}"}, body={"analysis_json": data, "progress": payload.progress, "stage": "analyzing", "message": payload.message})
    return {"ok": True, "saved_chunks": len(data["chunks"]), "progress": rows[0].get("progress")}


@app.post("/api/worker/jobs/{job_id}/script-ready")
def worker_script_ready(job_id: str, payload: ScriptReady, _: None = Depends(check_worker)):
    get_job(job_id)
    rows = db_request("PATCH", "recap_jobs", params={"id": f"eq.{job_id}"}, body={
        "status": "awaiting_approval",
        "progress": 48,
        "stage": "script_review",
        "message": "AI Script ရေးပြီးပါပြီ။ Lovable App ထဲမှာ စစ်ဆေး/ပြင်ဆင်ပြီး Approve လုပ်ပါ။",
        "script_text": payload.script_text,
        "analysis_json": payload.analysis_json,
        "highlights_json": payload.highlights_json,
    })
    return public_job(rows[0])


@app.post("/api/worker/jobs/{job_id}/complete")
def worker_complete(job_id: str, payload: WorkerComplete, _: None = Depends(check_worker)):
    get_job(job_id)
    file_id = extract_drive_id(payload.result_drive_file_id)
    result_url = f"https://drive.google.com/file/d/{file_id}/view"
    rows = db_request("PATCH", "recap_jobs", params={"id": f"eq.{job_id}"}, body={
        "status": "completed", "progress": 100, "stage": "completed",
        "message": "1080p Recap Video Export ပြီးပါပြီ။",
        "result_drive_file_id": file_id, "result_filename": payload.result_filename,
        "result_url": result_url, "error_message": None,
    })
    return public_job(rows[0])


@app.post("/api/worker/jobs/{job_id}/fail")
def worker_fail(job_id: str, payload: WorkerFailure, _: None = Depends(check_worker)):
    get_job(job_id)
    rows = db_request("PATCH", "recap_jobs", params={"id": f"eq.{job_id}"}, body={
        "status": "failed", "stage": "failed", "message": "အလုပ်မပြီးဆုံးပါ။ Error ကို စစ်ဆေးပါ။",
        "error_message": payload.error_message, "progress": 0,
    })
    return public_job(rows[0])
