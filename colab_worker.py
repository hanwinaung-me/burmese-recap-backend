"""Colab-side worker for Burmese Recap Studio.

Run this in Google Colab after installing requirements and authenticating Google Drive.
It does the heavy work; the Render API only stores jobs and progress.
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

import requests

API_BASE_URL = os.getenv("API_BASE_URL", "").rstrip("/")
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "Charon")
ANALYSIS_CHUNK_SECONDS = int(os.getenv("ANALYSIS_CHUNK_SECONDS", "480"))
TTS_CHUNK_CHARS = int(os.getenv("TTS_CHUNK_CHARS", "2400"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "20"))

WORK_ROOT = Path("/content/burmese_recap_work")
WORK_ROOT.mkdir(parents=True, exist_ok=True)


def log(message: str) -> None:
    print(f"[Burmese Recap Worker] {message}", flush=True)


def run_command(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and result.returncode != 0:
        tail = (result.stderr or result.stdout or "Unknown FFmpeg error")[-5000:]
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command[:5])}\n{tail}")
    return result


def api_headers() -> dict[str, str]:
    return {"X-Worker-Token": WORKER_TOKEN, "Content-Type": "application/json"}


def api_post(path: str, body: dict | None = None, timeout: int = 90) -> dict:
    response = requests.post(f"{API_BASE_URL}{path}", headers=api_headers(), json=body or {}, timeout=timeout)
    if response.status_code >= 400:
        raise RuntimeError(f"API {path} failed ({response.status_code}): {response.text[:1500]}")
    return response.json() if response.content else {}


def api_progress(job_id: str, progress: int, stage: str, message: str) -> None:
    api_post(f"/api/worker/jobs/{job_id}/progress", {
        "progress": max(0, min(99, int(progress))),
        "stage": stage,
        "message": message[:500],
    })


def build_google_clients():
    try:
        from googleapiclient.discovery import build
        from google.auth import default as google_auth_default
    except ImportError as exc:
        raise RuntimeError("Google Drive packages မရှိပါ။ Colab setup cell ကို အရင် run ပါ။") from exc
    credentials, _ = google_auth_default(scopes=["https://www.googleapis.com/auth/drive"])
    drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return drive_service


def download_drive_file(drive_service, file_id: str, destination: Path) -> dict:
    from googleapiclient.http import MediaIoBaseDownload

    metadata = drive_service.files().get(
        fileId=file_id,
        fields="id,name,mimeType,size",
        supportsAllDrives=True,
    ).execute()
    mime_type = metadata.get("mimeType", "")
    if not (mime_type.startswith("video/") or mime_type.startswith("audio/")):
        raise RuntimeError(f"Drive file က Video/Audio မဟုတ်ပါ။ Detected type: {mime_type}")
    request = drive_service.files().get_media(fileId=file_id, supportsAllDrives=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        downloader = MediaIoBaseDownload(handle, request, chunksize=16 * 1024 * 1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                log(f"Drive download: {int(status.progress() * 100)}%")
    if not destination.exists() or destination.stat().st_size < 1024:
        raise RuntimeError("Google Drive မှ Video ကို အပြည့်အစုံ download မရပါ။")
    return metadata


def ensure_drive_folder(drive_service, folder_name: str = "BurmeseRecapExports") -> str:
    query = (
        "mimeType='application/vnd.google-apps.folder' "
        f"and name='{folder_name}' and trashed=false"
    )
    result = drive_service.files().list(q=query, spaces="drive", fields="files(id,name)", pageSize=10).execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]
    created = drive_service.files().create(
        body={"name": folder_name, "mimeType": "application/vnd.google-apps.folder"},
        fields="id",
    ).execute()
    return created["id"]


def upload_to_drive(drive_service, path: Path, folder_id: str, filename: str) -> dict:
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(str(path), mimetype="video/mp4", resumable=True, chunksize=8 * 1024 * 1024)
    request = drive_service.files().create(
        body={"name": filename, "parents": [folder_id], "mimeType": "video/mp4"},
        media_body=media,
        fields="id,name,webViewLink,size",
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log(f"Google Drive export upload: {int(status.progress() * 100)}%")
    return response


def get_duration(path: Path) -> float:
    result = run_command([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ])
    try:
        return float(result.stdout.strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Video ကြာချိန်ကို ffprobe နဲ့ မဖတ်နိုင်ပါ။") from exc


def new_gemini_client():
    from google import genai
    return genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1beta"})


def retry_call(func, *, attempts: int = 7, label: str = "AI request"):
    last_error = None
    for attempt in range(attempts):
        try:
            return func()
        except Exception as exc:  # retry rate limits / transient service interruptions
            last_error = exc
            message = str(exc)
            permanent = any(code in message for code in ["400 INVALID_ARGUMENT", "401", "403", "API_KEY_INVALID", "PERMISSION_DENIED", "NOT_FOUND"])
            if permanent or attempt == attempts - 1:
                break
            delay = min(90, 8 * (2 ** attempt))
            log(f"{label} မအောင်မြင်ပါ။ {delay}s နောက် ပြန်ကြိုးစားမယ်။ ({message[:250]})")
            time.sleep(delay)
    raise RuntimeError(f"{label} မအောင်မြင်ပါ: {last_error}")


def parse_json_text(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise RuntimeError("AI က JSON ပုံစံနဲ့ မပြန်ပေးပါ။")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise RuntimeError("AI JSON ရလဒ်က object မဟုတ်ပါ။")
    return value


def make_analysis_clip(source: Path, clip_path: Path, start: float, length: float) -> None:
    # A lightweight 1-fps proxy keeps long uploads smaller while retaining visual chronology.
    vf = "fps=1,scale='min(960,iw)':-2"
    run_command([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{length:.3f}",
        "-map", "0:v:0", "-map", "0:a?", "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-r", "1", "-g", "1",
        "-c:a", "aac", "-b:a", "48k", "-ac", "1", "-ar", "16000",
        "-movflags", "+faststart", str(clip_path),
    ])


def analyze_one_chunk(client, clip_path: Path, chunk_index: int, offset: float, clip_length: float) -> dict:
    from google.genai import types

    uploaded = None
    try:
        uploaded = client.files.upload(file=str(clip_path))
        deadline = time.time() + 20 * 60
        while True:
            state = getattr(uploaded, "state", None)
            state_name = getattr(state, "name", str(state)).upper() if state is not None else "PROCESSING"
            if state_name == "ACTIVE":
                break
            if state_name == "FAILED":
                raise RuntimeError(f"Gemini File API က အပိုင်း {chunk_index + 1} ကို process မလုပ်နိုင်ပါ။")
            if time.time() > deadline:
                raise RuntimeError("Gemini File API processing ကြာလွန်းနေပါတယ်။")
            time.sleep(5)
            uploaded = client.files.get(name=uploaded.name)

        prompt = f"""
You are analyzing one chronological segment from a film/video for a Burmese recap.
This clip is segment number {chunk_index + 1}. It begins at {offset:.1f} seconds in the ORIGINAL full video and lasts {clip_length:.1f} seconds.

TASK:
1. Describe only events actually visible/audible in this clip, in chronological order.
2. Track characters only when their identity is evident. Do not invent names, motives, dialogue, or unseen events.
3. Return enough concrete plot detail for a later long-form Burmese recap writer.
4. Select 4 to 8 useful visual highlight intervals from THIS CLIP for the recap edit. Use local clip seconds, not original full-video seconds. Each interval should be about 7 to 18 seconds and must stay within 0 to {clip_length:.1f}.
5. Avoid repeatedly selecting the same static scene. Prefer events, reactions, setting changes, reveals, and important actions.

Return valid JSON only, with this exact shape:
{{
  "summary": "Detailed chronological summary",
  "events": ["event 1", "event 2"],
  "characters": ["visible character description; name only if known"],
  "uncertainties": ["anything unclear; [] if none"],
  "highlights": [{{"start_sec": 5.0, "end_sec": 16.0, "reason": "what this visual shows"}}]
}}

Write summary/events in English or Burmese, but keep all factual details exact. Do not reproduce long dialogue or copyrighted screenplay text.
""".strip()

        def request():
            return client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_uri(file_uri=uploaded.uri, mime_type=uploaded.mime_type),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                    max_output_tokens=5000,
                ),
            )

        response = retry_call(request, label=f"Video analysis part {chunk_index + 1}")
        data = parse_json_text(getattr(response, "text", ""))
        valid_highlights = []
        for item in data.get("highlights", []) or []:
            try:
                start = max(0.0, float(item.get("start_sec", 0)))
                end = min(float(clip_length), float(item.get("end_sec", 0)))
                if end - start >= 5:
                    valid_highlights.append({
                        "start_sec": start,
                        "end_sec": end,
                        "reason": str(item.get("reason", ""))[:250],
                    })
            except (TypeError, ValueError, AttributeError):
                continue
        data["highlights"] = valid_highlights
        data["chunk_index"] = chunk_index
        data["offset_seconds"] = offset
        return data
    finally:
        if uploaded is not None:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass


def build_script(client, analysis_chunks: list[dict], target_minutes: int, movie_title: str) -> str:
    from google.genai import types

    condensed = []
    for item in sorted(analysis_chunks, key=lambda row: int(row.get("chunk_index", 0))):
        condensed.append({
            "part": int(item.get("chunk_index", 0)) + 1,
            "time_offset_seconds": item.get("offset_seconds", 0),
            "summary": item.get("summary", ""),
            "events": item.get("events", []),
            "characters": item.get("characters", []),
            "uncertainties": item.get("uncertainties", []),
        })
    prompt = f"""
သင်သည် မြန်မာဘာသာ Movie Recap ဇာတ်ညွှန်းရေးသားသူဖြစ်သည်။ မူရင်းဇာတ်ကားကို အစားထိုးမည့် ဇာတ်ညွှန်းမဟုတ်ဘဲ ကိုယ်ပိုင်သုံးသပ်ချက်၊ ရှင်းလင်းချက်နှင့် အကျဉ်းချုပ်ပါသော အသစ်ရေးသားသည့် Recap Narration ကို ဖန်တီးပါ။

ဇာတ်ကား/ဗီဒီယိုအမည်: {movie_title or 'မသိရှိရသေး'}
ရည်မှန်းထားသော Narration ကြာချိန်: {target_minutes} မိနစ်ခန့်။

အောက်ပါအချက်အလက်များသည် ဗီဒီယိုကို အပိုင်းလိုက်ကြည့်ပြီး မှတ်တမ်းတင်ထားခြင်းဖြစ်သည်။ အပိုင်းအစီအစဉ်အတိုင်း အစမှအဆုံး ဇာတ်လမ်းဆက်စပ်မှုကို ထိန်းသိမ်းပါ။
{json.dumps(condensed, ensure_ascii=False)}

ရေးသားရန် စည်းကမ်းများ:
- မြန်မာစကားပြောသံနှင့် သဘာဝကျသော ပုံစံဖြင့် ရေးပါ။ စက်ရုပ်ဆန်သော ဘာသာပြန်သံ မဖြစ်စေရ။
- စတင်ချိန်တွင် စိတ်ဝင်စားစေမည့် Hook တစ်ခု ထည့်ပါ။ ပြီးလျှင် ဇာတ်လမ်းကို အစဉ်လိုက် ရှင်းပြပြီး အမှန်တကယ် မြင်တွေ့ထားသည့် အဆုံးသတ်အထိ ရေးပါ။
- စကားပြောခန်းရှည်များကို တိုက်ရိုက်မကူးပါနှင့်။ ကိုယ်ပိုင်စကားဖြင့် ပြန်လည်ရှင်းပြပါ။
- Analysis ထဲမပါသော အဖြစ်အပျက်၊ ဇာတ်ကောင်နာမည်၊ အကြောင်းရင်း၊ အဆုံးသတ်ကို မတီထွင်ပါနှင့်။ မသေချာသည့်နေရာကို အတည်မပြုနိုင်သလို ရေးပါ။
- ဇာတ်လမ်းကို အပိုင်းလိုက် bullet မလုပ်ဘဲ နားထောင်ရလွယ်သော ဆက်တိုက် Narration အဖြစ်ရေးပါ။ လိုအပ်သောနေရာတွင် သဘာဝကျသော အပိုဒ်ခွဲများသာ သုံးပါ။
- ဇာတ်ကားတစ်ကားလုံးကို အစားထိုးကြည့်ရှုနိုင်လောက်အောင် အသေးစိတ် ပြန်လည်ဖော်ပြခြင်း၊ မူရင်းဇာတ်ညွှန်း/Dialogue ကို ကူးယူခြင်း မလုပ်ပါနှင့်။
- မူပိုင်ခွင့်ကင်းလွတ်သည်၊ Copyright-free ဖြစ်သည်၊ Monetization အာမခံသည်ဟု မဆိုပါနှင့်။
- Output တွင် ဇာတ်ညွှန်းစာသားသာ ပါရမည်။ ခေါင်းစဉ်၊ Markdown, Note, AI အကြောင်း ရှင်းလင်းချက် မထည့်ပါနှင့်။
""".strip()

    def request():
        return client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.65, max_output_tokens=8192),
        )

    response = retry_call(request, label="Burmese script generation")
    script = (getattr(response, "text", "") or "").strip()
    script = re.sub(r"^```[\w-]*\s*|\s*```$", "", script, flags=re.S).strip()
    if len(script) < 500:
        raise RuntimeError("AI Script အရှည် မလုံလောက်ပါ။ API quota/model ရလဒ်ကို စစ်ပါ။")
    return script


def split_burmese_text(text: str, max_chars: int = TTS_CHUNK_CHARS) -> list[str]:
    cleaned = re.sub(r"[\*#`_]{1,3}", "", text).strip()
    sentences = re.split(r"(?<=[။!?])\s*", cleaned)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            # Split oversized sentence at spaces; if no spaces exist, use character blocks.
            pieces = re.split(r"(?<=\s)", sentence)
            buf = ""
            for piece in pieces:
                if len(buf) + len(piece) > max_chars and buf:
                    chunks.append(buf.strip())
                    buf = piece
                else:
                    buf += piece
            if buf.strip():
                chunks.append(buf.strip())
            continue
        if len(current) + len(sentence) + 1 > max_chars and current:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def make_tts_audio(client, script: str, out_dir: Path, voice: str, job_id: str) -> Path:
    """Generate Burmese narration with Gemini TTS and join WAV chunks safely."""
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks = split_burmese_text(script)
    if not chunks:
        raise RuntimeError("Voice ထုတ်ရန် Script မရှိပါ။")
    wav_paths = []
    total = len(chunks)
    chosen_voice = voice or DEFAULT_VOICE

    for index, text in enumerate(chunks):
        log(f"Burmese AI Voice: {index + 1}/{total}")
        api_progress(
            job_id,
            54 + int((index / max(1, total)) * 9),
            "voice",
            f"Burmese AI Voice {index + 1}/{total}",
        )
        style = (
            "Professional Burmese male movie recap narrator; mature warm resonant mid-low voice; "
            "clear natural Myanmar pronunciation; slightly slow measured pacing; "
            "suspenseful but controlled; confident and expressive without shouting; "
            "clean studio narration; do not imitate any real person."
        )

        def request():
            return client.interactions.create(
                model=GEMINI_TTS_MODEL,
                input=[{
                    "type": "user_input",
                    "content": [{
                        "type": "text",
                        "text": text,
                        "annotations": [{"type": "speech_metadata", "style": style}],
                    }],
                }],
                response_format={"type": "audio"},
                generation_config={"speech_config": [{"voice": chosen_voice}]},
            )

        interaction = retry_call(request, label=f"TTS chunk {index + 1}")
        audio_obj = getattr(interaction, "output_audio", None)
        audio_data = getattr(audio_obj, "data", None) if audio_obj is not None else None
        if not audio_data and isinstance(audio_obj, dict):
            audio_data = audio_obj.get("data")
        if not audio_data:
            raise RuntimeError("Gemini TTS မှ Audio data မရပါ။ API response ကို စစ်ပါ။")
        wav_bytes = audio_data if isinstance(audio_data, bytes) else base64.b64decode(audio_data)

        wav_path = out_dir / f"voice_{index:04d}.wav"
        wav_path.write_bytes(wav_bytes)
        normalized = out_dir / f"voice_{index:04d}_normalized.wav"
        run_command([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav_path),
            "-vn", "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(normalized),
        ])
        wav_paths.append(normalized)

    concat_list = out_dir / "audio_concat.txt"
    concat_list.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in wav_paths),
        encoding="utf-8",
    )
    joined = out_dir / "narration_joined.wav"
    run_command([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
        "-safe", "0", "-i", str(concat_list), "-c:a", "pcm_s16le", str(joined),
    ])
    final_audio = out_dir / "narration.m4a"
    run_command([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(joined),
        "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k", str(final_audio),
    ])
    return final_audio


def transcribe_for_subtitles(audio_path: Path, work_dir: Path) -> list[dict]:
    try:
        import torch
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Subtitle အတွက် faster-whisper မရှိပါ။ Colab setup cell ကို run ပါ။") from exc

    has_cuda = bool(torch.cuda.is_available())
    device = "cuda" if has_cuda else "cpu"
    compute_type = "float16" if has_cuda else "int8"
    log(f"Subtitle transcription စတင်: device={device}")
    model = WhisperModel("small", device=device, compute_type=compute_type, download_root=str(work_dir / "whisper_model"))
    segments, info = model.transcribe(
        str(audio_path),
        language="my",
        beam_size=5,
        vad_filter=True,
        word_timestamps=False,
        condition_on_previous_text=True,
    )
    output = []
    for segment in segments:
        text = (segment.text or "").strip()
        if text:
            output.append({"start": float(segment.start), "end": float(segment.end), "text": text})
    if not output:
        raise RuntimeError("Voice မှ Subtitle စာသား မရပါ။ မြန်မာအသံကို Whisper က မဖမ်းနိုင်ခဲ့ပါ။")
    return output


def hex_to_ass_colour(hex_colour: str, alpha: int = 0) -> str:
    value = hex_colour.lstrip("#")
    red, green, blue = value[0:2], value[2:4], value[4:6]
    return f"&H{alpha:02X}{blue}{green}{red}".upper()


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    centiseconds = int(round(seconds * 100))
    hours = centiseconds // 360000
    minutes = (centiseconds // 6000) % 60
    secs = (centiseconds // 100) % 60
    cs = centiseconds % 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    text = str(text).replace("\\", "／").replace("{", "｛").replace("}", "｝")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def create_ass_subtitles(
    segments: list[dict], output_path: Path, duration: float, settings: dict,
) -> None:
    sub_colour = hex_to_ass_colour(settings.get("subtitle_color", "#FFFFFF"))
    outline_colour = hex_to_ass_colour(settings.get("subtitle_outline_color", "#000000"))
    font_size = int(settings.get("subtitle_font_size", 48))
    position = settings.get("subtitle_position", "bottom")
    alignment = {"bottom": 2, "top": 8, "middle": 5}.get(position, 2)
    channel = ass_escape(settings.get("channel_name", "Burmese Recap"))
    watermark_enabled = bool(settings.get("watermark_enabled", True))
    watermark_opacity = int(settings.get("watermark_opacity", 65))
    watermark_alpha = max(0, min(255, round(255 * (100 - watermark_opacity) / 100)))
    watermark_colour = hex_to_ass_colour("#FFFFFF", watermark_alpha)
    watermark_font_size = max(24, int(font_size * 0.72))

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "\n[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Noto Sans Myanmar,{font_size},{sub_colour},&H0000FFFF,{outline_colour},&H80000000,-1,0,0,0,100,100,0,0,1,3,1,{alignment},90,90,70,1",
        f"Style: Watermark,Noto Sans Myanmar,{watermark_font_size},{watermark_colour},&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,9,55,55,55,1",
        "\n[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if watermark_enabled and channel:
        watermark = f"{{\\an9\\pos(1860,55)}}{channel}"
        lines.append(f"Dialogue: 1,{ass_time(0)},{ass_time(max(duration, 1))},Watermark,,0,0,0,,{watermark}")
    for item in segments:
        start = max(0.0, float(item.get("start", 0)))
        end = min(duration, max(start + 0.25, float(item.get("end", start + 1))))
        text = ass_escape(item.get("text", ""))
        if text and end > start:
            lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{text}")
    output_path.write_text("\n".join(lines), encoding="utf-8-sig")


def merge_intervals(intervals: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    cleaned = []
    for start, end in intervals:
        start = max(0.0, min(duration, float(start)))
        end = max(start, min(duration, float(end)))
        if end - start >= 4:
            cleaned.append((start, end))
    cleaned.sort(key=lambda item: item[0])
    merged: list[list[float]] = []
    for start, end in cleaned:
        if merged and start <= merged[-1][1] + 1.0:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(item[0], item[1]) for item in merged]


def build_montage(source: Path, highlights: list[dict], video_duration: float, audio_duration: float, out_path: Path) -> None:
    intervals = []
    for item in highlights or []:
        try:
            start = float(item.get("start_seconds", item.get("start", 0)))
            end = float(item.get("end_seconds", item.get("end", 0)))
            if end - start > 0:
                intervals.append((start, end))
        except (TypeError, ValueError, AttributeError):
            continue

    intervals = merge_intervals(intervals, video_duration)
    selected = sum(end - start for start, end in intervals)
    # If AI selected too little footage, add evenly-spaced contextual shots from the source.
    needed = audio_duration - selected + 3
    if needed > 0:
        sample_length = min(12.0, max(6.0, needed / max(1, math.ceil(needed / 10))))
        steps = max(15.0, video_duration / max(1, int(needed / sample_length) + 2))
        cursor = steps / 2
        attempts = 0
        while needed > 0 and cursor < video_duration - 3 and attempts < 1000:
            candidate = (max(0.0, cursor), min(video_duration, cursor + sample_length))
            overlaps = any(not (candidate[1] <= a or candidate[0] >= b) for a, b in intervals)
            if not overlaps and candidate[1] - candidate[0] >= 5:
                intervals.append(candidate)
                needed -= candidate[1] - candidate[0]
            cursor += steps
            attempts += 1
        intervals = merge_intervals(intervals, video_duration)

    if not intervals:
        intervals = [(0.0, min(video_duration, max(10.0, audio_duration)))]

    # The select filter keeps only chosen original-time ranges, then resets timestamps
    # so the retained footage becomes a chronological montage without source audio.
    expression = "+".join(f"between(t\\,{start:.3f}\\,{end:.3f})" for start, end in intervals)
    vf = (
        f"fps=30,select='{expression}',setpts=N/(30*TB),"
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
    )
    run_command([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-vf", vf, "-an", "-t", f"{audio_duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(out_path),
    ])
    if not out_path.exists() or out_path.stat().st_size < 100_000:
        raise RuntimeError("Highlight Montage မထွက်လာပါ။ FFmpeg select filter ကို စစ်ပါ။")


def render_final_video(
    source: Path, script: str, highlights: list[dict], settings: dict, work_dir: Path,
    drive_service, job_id: str,
) -> tuple[Path, str]:
    client = new_gemini_client()
    api_progress(job_id, 54, "voice", "မြန်မာ AI Voice ထုတ်နေပါတယ်။")
    narration = make_tts_audio(client, script, work_dir / "tts", settings.get("voice", DEFAULT_VOICE), job_id)
    audio_duration = get_duration(narration)
    api_progress(job_id, 66, "subtitles", "Voice ကို အခြေခံပြီး Subtitle Timestamp ထုတ်နေပါတယ်။")
    subtitles = transcribe_for_subtitles(narration, work_dir)
    ass_file = work_dir / "subtitles.ass"
    create_ass_subtitles(subtitles, ass_file, audio_duration, settings)

    api_progress(job_id, 75, "editing", "AI ရွေးထားသော Scene များကို 1080p Timeline အဖြစ် စီနေပါတယ်။")
    video_duration = get_duration(source)
    montage = work_dir / "montage_1080p.mp4"
    build_montage(source, highlights, video_duration, audio_duration, montage)

    bgm_id = settings.get("bgm_drive_file_id")
    bgm_path = None
    if bgm_id:
        api_progress(job_id, 82, "audio_mix", "Background Music ကို ထည့်နေပါတယ်။")
        bgm_path = work_dir / "background_music"
        download_drive_file(drive_service, bgm_id, bgm_path)

    final_path = work_dir / "recap_final_1080p.mp4"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(montage), "-i", str(narration)]
    if bgm_path is not None:
        cmd += ["-stream_loop", "-1", "-i", str(bgm_path)]
        audio_filter = "[1:a]volume=1.0[voice];[2:a]volume=0.12[bgm];[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    else:
        audio_filter = "[1:a]anull[aout]"
    ass_filter_path = ass_file.as_posix().replace(":", "\\:")
    cmd += [
        "-filter_complex", audio_filter,
        "-vf", f"ass={ass_filter_path}",
        "-map", "0:v:0", "-map", "[aout]",
        "-t", f"{audio_duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(final_path),
    ]
    run_command(cmd)
    if not final_path.exists() or final_path.stat().st_size < 500_000:
        raise RuntimeError("Final MP4 ကို မထုတ်နိုင်ပါ။ FFmpeg logs ကို စစ်ပါ။")
    return final_path, f"{audio_duration / 60:.1f} min"


def global_highlights_from_chunks(chunks: list[dict]) -> list[dict]:
    results = []
    for chunk in chunks:
        offset = float(chunk.get("offset_seconds", 0))
        for highlight in chunk.get("highlights", []) or []:
            try:
                start = offset + float(highlight.get("start_sec", 0))
                end = offset + float(highlight.get("end_sec", 0))
                if end > start:
                    results.append({
                        "start_seconds": start,
                        "end_seconds": end,
                        "reason": str(highlight.get("reason", ""))[:250],
                    })
            except (TypeError, ValueError, AttributeError):
                continue
    return sorted(results, key=lambda item: item["start_seconds"])


def process_analysis_job(job: dict, drive_service, job_dir: Path) -> None:
    from google import genai

    job_id = job["id"]
    settings = job.get("settings") or {}
    source = job_dir / "source_video"
    if not source.exists():
        api_progress(job_id, 3, "download", "Google Drive မှ မူရင်း Video ကို download လုပ်နေပါတယ်။")
        metadata = download_drive_file(drive_service, job["source_drive_file_id"], source)
        log(f"Source: {metadata.get('name')} | {metadata.get('size', 'unknown')} bytes")

    duration = get_duration(source)
    if duration < 60:
        raise RuntimeError("Video သည် ၁ မိနစ်ထက်တိုနေပါတယ်။")
    total_chunks = math.ceil(duration / ANALYSIS_CHUNK_SECONDS)
    existing_data = job.get("analysis_json") or {"chunks": []}
    existing = list(existing_data.get("chunks", []))
    done_indexes = {int(item.get("chunk_index", -1)) for item in existing if isinstance(item, dict)}
    client = new_gemini_client()

    for index in range(total_chunks):
        if index in done_indexes:
            continue
        start = index * ANALYSIS_CHUNK_SECONDS
        length = min(ANALYSIS_CHUNK_SECONDS, duration - start)
        clip_path = job_dir / f"analysis_{index:04d}.mp4"
        api_progress(job_id, min(5 + int(index / max(1, total_chunks) * 38), 44), "analyzing", f"AI သုံးသပ်နေပါတယ်။ အပိုင်း {index + 1}/{total_chunks}")
        make_analysis_clip(source, clip_path, start, length)
        chunk_data = analyze_one_chunk(client, clip_path, index, start, length)
        try:
            clip_path.unlink(missing_ok=True)
        except Exception:
            pass
        existing = [item for item in existing if int(item.get("chunk_index", -1)) != index]
        existing.append(chunk_data)
        progress = min(5 + int(len(existing) / max(1, total_chunks) * 38), 44)
        api_post(f"/api/worker/jobs/{job_id}/analysis-chunk", {
            "chunk_index": index,
            "chunk_data": chunk_data,
            "progress": progress,
            "message": f"AI သုံးသပ်ပြီးပါပြီ။ {len(existing)}/{total_chunks} အပိုင်း",
        })

    existing.sort(key=lambda item: int(item.get("chunk_index", 0)))
    api_progress(job_id, 45, "writing_script", "အစအဆုံး ဇာတ်လမ်းကို မြန်မာ Recap Script အဖြစ် ရေးနေပါတယ်။")
    script = build_script(client, existing, int(settings.get("target_minutes", 12)), job.get("movie_title") or job.get("source_filename", ""))
    highlights = global_highlights_from_chunks(existing)
    api_post(f"/api/worker/jobs/{job_id}/script-ready", {
        "script_text": script,
        "analysis_json": {"chunks": existing, "video_duration_seconds": duration},
        "highlights_json": highlights,
    })
    log(f"Job {job_id}: Script ready. Lovable App ထဲမှာ ပြင်ပြီး Approve လုပ်ပါ။")


def process_render_job(job: dict, drive_service, job_dir: Path) -> None:
    job_id = job["id"]
    source = job_dir / "source_video"
    settings = job.get("settings") or {}
    if not source.exists():
        api_progress(job_id, 52, "download", "Render အတွက် Google Drive မှ Video ကို ပြန် download လုပ်နေပါတယ်။")
        download_drive_file(drive_service, job["source_drive_file_id"], source)
    script = (job.get("script_text") or "").strip()
    if len(script) < 50:
        raise RuntimeError("အတည်ပြုထားသော Script မရှိပါ။ Lovable မှ Script ကို Approve ပြန်လုပ်ပါ။")
    highlights = job.get("highlights_json") or []
    final_path, duration_label = render_final_video(source, script, highlights, settings, job_dir, drive_service, job_id)
    api_progress(job_id, 92, "upload", "1080p MP4 ကို Google Drive ထဲ upload လုပ်နေပါတယ်။")
    folder_id = ensure_drive_folder(drive_service)
    base_title = job.get("movie_title") or Path(job.get("source_filename", "recap")).stem
    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "_", base_title).strip("_")[:60] or "movie_recap"
    channel = re.sub(r"[^A-Za-z0-9_-]+", "_", str(settings.get("channel_name", "BurmeseRecap"))).strip("_")[:40] or "BurmeseRecap"
    output_name = f"{safe_title}_{channel}_1080p.mp4"
    uploaded = upload_to_drive(drive_service, final_path, folder_id, output_name)
    api_post(f"/api/worker/jobs/{job_id}/complete", {
        "result_drive_file_id": uploaded["id"],
        "result_filename": uploaded.get("name", output_name),
    })
    log(f"Job {job_id}: Export complete ({duration_label})")
    log(uploaded.get("webViewLink", "Google Drive upload complete"))


def process_job(job: dict, drive_service) -> None:
    job_id = job["id"]
    job_dir = WORK_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    try:
        if (job.get("script_text") or "").strip():
            process_render_job(job, drive_service, job_dir)
        else:
            process_analysis_job(job, drive_service, job_dir)
    except Exception as exc:
        message = f"{exc.__class__.__name__}: {exc}\n{traceback.format_exc()[-2500:]}"
        log(message)
        try:
            api_post(f"/api/worker/jobs/{job_id}/fail", {"error_message": message[:1900]})
        except Exception as api_exc:
            log(f"Could not report failure to API: {api_exc}")


def run_worker() -> None:
    if not API_BASE_URL or not WORKER_TOKEN or not GEMINI_API_KEY:
        raise RuntimeError("API_BASE_URL, WORKER_TOKEN, GEMINI_API_KEY တို့ကို Notebook မှာ သတ်မှတ်ပါ။")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("FFmpeg/FFprobe မတွေ့ပါ။ Colab setup cell ကို run ပါ။")

    drive_service = build_google_clients()
    log("Colab Worker စတင်ပါပြီ။ Job အသစ်ကို စောင့်နေပါတယ်။")
    while True:
        try:
            response = api_post("/api/worker/claim", {}, timeout=90)
            job = response.get("job")
            if not job:
                time.sleep(POLL_SECONDS)
                continue
            log(f"Claimed job: {job.get('id')} | status={job.get('status')} | source={job.get('source_filename')}")
            process_job(job, drive_service)
        except KeyboardInterrupt:
            log("Worker ကို user က ရပ်လိုက်ပါတယ်။")
            break
        except Exception as exc:
            log(f"Polling error: {exc}")
            time.sleep(max(POLL_SECONDS, 30))


if __name__ == "__main__":
    run_worker()
