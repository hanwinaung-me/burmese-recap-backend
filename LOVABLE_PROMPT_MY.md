# Lovable ထဲမှာ တစ်ခါတည်း Paste လုပ်ရန် Prompt

Build a complete, mobile-first web app named **Burmese Recap Studio**. The user interface language must be Burmese (Myanmar), with clear Myanmar font support (Noto Sans Myanmar), a polished dark cinematic editing-studio design, responsive for Android phones, and accessible controls.

IMPORTANT ARCHITECTURE:
- This is a frontend only. Do NOT create a new Supabase database, do NOT use Lovable Cloud database, and do NOT put Gemini keys, Supabase service-role keys, or worker tokens in the browser.
- The backend is a FastAPI API hosted on Render. API base URL must be configured by the owner in a Settings screen and saved in localStorage. Do not hard-code a fake URL.
- Implement a small API helper in `src/lib/api.ts` with `getApiBaseUrl()`, `setApiBaseUrl()`, and `apiFetch(path, options)`. `apiFetch` must attach `Authorization: Bearer <token>` after login, send JSON, parse JSON errors, and show useful Burmese error messages. Store the login token in localStorage under `recap_access_token`.
- The user is the only account. Login is a single password sent to `POST /api/auth/login` as `{ "password": "..." }`. Store `access_token` from the response. Never add public sign-up.

PAGES / FEATURES:
1. **Setup / Login screen**
   - First show an API Server URL field if no API URL is saved. It must accept a URL such as `https://your-api-name.onrender.com`, remove any trailing slash, save it, and test `GET /health`.
   - Show API status from `/health` and a Burmese explanation when the server is asleep / starting.
   - Then show one password field and Login button calling `POST /api/auth/login`.
   - Never ask the user to enter GEMINI_API_KEY or WORKER_TOKEN in this app.

2. **Dashboard**
   - Call `GET /api/jobs` and show recent jobs as mobile-friendly cards with filename, movie title, status, progress bar, stage, date, and message.
   - Poll active jobs every 10 seconds while the page is visible. Stop polling when there are no active jobs or the user logs out.
   - Status labels in Burmese: queued=စောင့်ဆိုင်းနေ, processing=လုပ်ဆောင်နေ, awaiting_approval=ဇာတ်ညွှန်းစစ်ဆေးရန်, approved=Export စောင့်ဆိုင်းနေ, completed=ပြီးစီး, failed=မအောင်မြင်.
   - Clicking a card opens its job detail.

3. **Create New Recap Job page**
   - Add a button/link to open Google Drive upload: `https://drive.google.com/drive/my-drive`.
   - Explain that large videos must first be uploaded to the owner's Google Drive. Keep the file Restricted/private; the Google account used to authorize Colab must have access. The user then copies the Drive share link and pastes it into the Drive File ID/link field. This is not a direct browser upload.
   - Fields must exactly match the backend API:
     `{ source_drive_file_id, source_filename, movie_title, target_minutes, channel_name, watermark_enabled, watermark_opacity, subtitle_color, subtitle_outline_color, subtitle_font_size, subtitle_position, voice, bgm_drive_file_id, rights_confirmed }`.
   - `source_drive_file_id`: required text field; accepts a Google Drive file ID or full share URL.
   - `source_filename`: required filename shown in Drive.
   - `movie_title`: optional title.
   - `target_minutes`: numeric selector from 5 to 30, default 12.
   - `channel_name`: required. This will be written on the finished video as the owner/channel watermark.
   - `watermark_enabled`: default true; show a live preview; `watermark_opacity` range 10–100, default 65.
   - `subtitle_color` and `subtitle_outline_color`: native color pickers, default white text and black outline.
   - `subtitle_font_size`: slider 28–80, default 48.
   - `subtitle_position`: bottom/top/middle, default bottom.
   - `voice`: dropdown with `Charon`, `Kore`, `Puck`, `Aoede`; default `Charon`.
   - `bgm_drive_file_id`: optional Drive file ID/link for a music track the user is licensed to use.
   - `rights_confirmed`: required checkbox stating the user owns the footage, has a license, or otherwise has permission to use it. Do not say that Recap automatically makes copyrighted material legal or guarantees monetization.
   - On Submit call `POST /api/jobs` with the JSON fields. Show the returned job id and navigate to the detail page.

4. **Job Detail / Script Review page**
   - Call `GET /api/jobs/:id`, refresh every 10 seconds while status is `queued`, `processing`, `approved`.
   - When status is `awaiting_approval`, show a large editable Burmese script textarea prefilled with `script_text`.
   - Save button calls `PATCH /api/jobs/:id/script` with `{ "script_text": "..." }`.
   - Show subtitle design controls while awaiting approval. Save button calls `PATCH /api/jobs/:id/settings` with the changed setting keys only.
   - Show the AI-selected scene list using `highlights_json`. Each scene card must show start/end seconds and reason. Let the owner remove a scene, restore it while editing, and change start/end seconds (limit each scene to 180 seconds). Provide Add Scene by entering start/end seconds and a short reason. Save selected scene edits by calling `PATCH /api/jobs/:id/highlights` with `{ "highlights_json": [{ "start_seconds": 12.0, "end_seconds": 24.0, "reason": "..." }] }`. Do not send deleted scenes. Clearly label this as scene-selection editing, not a frame-accurate drag timeline.
   - Add an Approve & Render button. It must first save unsaved script/settings, then call `POST /api/jobs/:id/approve`. Confirm with the user before sending this approval.
   - Show an explanation: after approval the Colab worker creates Burmese voice, transcribes the voice to subtitles, selects highlight scenes, burns subtitles/watermark, adds optional background music, and exports 1080p MP4.
   - If completed, show a prominent Open/Download Video link using `result_url` (open in new tab) and show `result_filename`.
   - If failed, show `error_message`, a Copy Error button, and a Retry button calling `POST /api/jobs/:id/retry`.

5. **Settings**
   - API base URL editable; save and test `/health`.
   - Logout button clears token.

DESIGN:
- Dark charcoal/navy background, tasteful violet/cyan accents, rounded cards, generous touch targets, clean typography.
- All primary actions accessible on mobile; no desktop-only hover controls.
- Use a side menu on desktop and bottom navigation on mobile (Dashboard, New Recap, Settings).
- Add a visible explanation that the app requires the Colab Worker Notebook to be running for processing. If no worker is polling, jobs stay queued or approved.
- Use clear loading, empty, success, and error states. Avoid fake progress: progress must come from API fields only.
- Do not invent API endpoints. Use only the exact endpoints listed above.

API ENDPOINTS:
- `GET /health` (no token)
- `POST /api/auth/login` `{password}`
- `GET /api/me` (Bearer token)
- `POST /api/jobs` (Bearer token; fields described above)
- `GET /api/jobs` (Bearer token)
- `GET /api/jobs/{id}` (Bearer token)
- `PATCH /api/jobs/{id}/script` `{script_text}` (Bearer token)
- `PATCH /api/jobs/{id}/settings` (Bearer token; supported keys: subtitle_color, subtitle_outline_color, subtitle_font_size, subtitle_position, watermark_enabled, watermark_opacity, channel_name, voice)
- `PATCH /api/jobs/{id}/highlights` `{highlights_json: [{start_seconds, end_seconds, reason}]}` (Bearer token)
- `POST /api/jobs/{id}/approve` (Bearer token)
- `POST /api/jobs/{id}/retry` (Bearer token; failed job only)

Please implement the full frontend, routing, typed API client, forms, validation, state management, and responsive styling. Do not leave placeholder buttons or fake interactions.
