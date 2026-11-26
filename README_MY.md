# Burmese Recap Studio — Project Bundle (v1.0.0)

ဒီ Project က Android ဖုန်းတစ်လုံးနဲ့ အခမဲ့စတင်တည်ဆောက်နိုင်ဖို့ ရည်ရွယ်ထားတဲ့ Single-owner Recap Studio ဖြစ်ပါတယ်။ Backend API ကို Render Free မှာတင်မယ်။ Job metadata နဲ့ editable Script ကို Supabase Free Database မှာထားမယ်။ မူရင်း Video နဲ့ Export Video ကို မောင့် Google Drive မှာထားမယ်။ FFmpeg, AI Video Analysis, Burmese Voice, Subtitle, Editing, 1080p Export ကို Google Colab မှာလုပ်မယ်။ Lovable က Frontend App ဖြစ်မယ်။

## အရေးကြီးတဲ့ Free-tier ကန့်သတ်ချက်

- Render Free Web Service က incoming request မရှိဘဲ ၁၅ မိနစ်နေရင် sleep ဖြစ်နိုင်ပြီး local files တွေ restart/redeploy မှာ ပျောက်နိုင်တယ်။ ဒီ Backend က Video မသိမ်းဘဲ job metadata ကိုသာ Supabase ထဲထားတာကြောင့် မူရင်း Video မပျောက်ပါ။
- Supabase Free မှာ Database 500 MB ပါဝင်ပြီး တစ်ပတ်ခန့် activity နည်းလျှင် project pause ဖြစ်နိုင်တယ်။ ဒီ project က video/audio သိမ်းမထားဘဲ metadata နဲ့ script သာသိမ်းမယ်။
- Colab Free က GPU/CPU, runtime, usage ကို အာမမခံပါ။ အများဆုံး runtime သည် လက်ရှိ FAQ အရ အခြေအနေပေါ်မူတည်၍ ၁၂ နာရီအထိသာဖြစ်နိုင်ပြီး ပြောင်းလဲနိုင်ပါတယ်။ Colab ကို Web App မှ remote content-generation worker အဖြစ် သုံးလျှင် runtime terminate ဖြစ်နိုင်ကြောင်း Google သတိပေးထားပါတယ်။ ဒါကြောင့် ဒီ setup ကို ကိုယ်တစ်ယောက်တည်း စမ်းသပ်အသုံးပြုရန် best-effort စနစ်အဖြစ်သာ သတ်မှတ်ပါ။
- Gemini API Free tier မှာ rate limit ရှိတယ်။ အရှည် ၂–၃ နာရီ Video တစ်ခုကို ၈ မိနစ်စီ proxy chunk ခွဲပြီး Analysis လုပ်ပေမဲ့ quota၊ runtime သို့မဟုတ် Colab disk မလုံလောက်ရင် Job မပြီးနိုင်ပါ။
- Gemini Developer API Free tier က ပို့လိုက်တဲ့ content ကို Google က product improvement အတွက် အသုံးပြုနိုင်တယ်လို့ pricing စာမျက်နှာမှာ ဖော်ပြထားတယ်။ ကိုယ်ရေးကိုယ်တာ/လျှို့ဝှက် Video များ မတင်ပါနှင့်။ အသုံးပြုခွင့်မရှိသောရုပ်ရှင်/ဗီဒီယိုများကို တင်ရန် မတိုက်တွန်းပါ။
- Subtitle ကို Burmese Whisper ASR နဲ့ ထုတ်ပေးပေမဲ့ စကားလုံးမှားနိုင်ပါတယ်။ Export မတိုင်မီ ပြန်စစ်ဖို့ လိုနိုင်ပါတယ်။
- Watermark က ကိုယ်ပိုင် Channel အမည်ကို Video ထဲထည့်ပေးတဲ့ အကာအကွယ်တစ်ခုသာဖြစ်ပြီး ဖျက်မရ/ကူးယူမရအောင် ၁၀၀% တားနိုင်တယ်လို့ မအာမခံပါ။
- Copyright ခွင့်ပြုချက်၊ Fair use/Fair dealing, YouTube Monetization ဆုံးဖြတ်ချက်တွေကို Tool က အာမမခံပါ။ မောင့်မှာ အသုံးပြုခွင့်ရှိတဲ့ footage/music ကိုသာ သုံးပါ။

## Project ဖိုင်တွေ

- `main.py` — FastAPI Backend API
- `requirements.txt` — Python packages
- `Dockerfile` — Render deployment
- `render.yaml` — Render Blueprint
- `supabase_schema.sql` — Supabase Database Table + Worker claim function
- `colab_worker.py` — Colab က Video/AI/Voice/Subtitle/Edit/Export လုပ်တဲ့ worker
- `colab_worker.ipynb` — Colab Notebook (run order နဲ့ secrets input ပါပြီးသား)
- `LOVABLE_PROMPT_MY.md` — Lovable ထဲ paste လုပ်ရန် Frontend prompt
- `.env.example` — Environment variables နမူနာ (အမှန်တကယ် secret မထည့်ပါနှင့်)

## အဆင့် 1 — Supabase Database ဖန်တီးရန်

1. https://supabase.com/dashboard ကိုဖွင့်ပြီး Free Project တစ်ခုဖန်တီးပါ။
2. Project တက်လာလျှင် ဘယ်ဘက်ရှိ **SQL Editor → New query** ကိုနှိပ်ပါ။
3. ZIP ထဲက `supabase_schema.sql` ဖိုင်အပြည့်ကို ဖွင့်ပြီး Copy လုပ်၊ SQL Editor ထဲ Paste လုပ်ပြီး **Run** နှိပ်ပါ။
4. **Project Settings → API Keys** ထဲက Project URL နဲ့ `sb_secret_...` လို့စတဲ့ **Secret key** ကိုယူပါ။ ရှိပြီးသား Project အဟောင်းမှာ Secret key မဖန်တီးရသေးရင် Legacy `service_role` JWT key ကို ယာယီသုံးနိုင်ပါတယ်။ ဒီ key ကို Lovable/Frontend သို့ GitHub ထဲ မထည့်ရပါ။ Render Environment ထဲမှာသာ ထည့်ပါ။

## အဆင့် 2 — GitHub ထဲ Backend တင်ရန်

1. https://github.com/new ကိုဖွင့်ပါ။
2. Repository name `burmese-recap-backend` ထည့်ပြီး **Private** ရွေးပါ။
3. ဖုန်းထဲ Project ZIP ကို Extract လုပ်ပါ။
4. ဖုန်းထဲက File Manager နဲ့ Project ZIP ကို Extract လုပ်ပါ။ GitHub Repository ထဲ **Add file → Upload files** ကိုနှိပ်ပြီး Extract လုပ်ထားတဲ့ Folder ထဲက ဖိုင်အားလုံးကို repository root အဆင့်မှာ တင်ပါ။ `main.py`, `Dockerfile`, `render.yaml`, `requirements.txt` တို့ဟာ တစ်နေရာတည်း root မှာ ရှိရပါမယ်။ `.env` ဖိုင် သို့မဟုတ် private API keys များကို GitHub ထဲ မတင်ပါနှင့်။

## အဆင့် 3 — Render Server Deploy လုပ်ရန်

1. https://dashboard.render.com/ ကိုဝင်ပြီး GitHub နဲ့ ချိတ်ပါ။
2. **New → Blueprint** ကိုရွေးပြီး `burmese-recap-backend` repository ကိုရွေးပါ။ `render.yaml` ကိုဖတ်ပြီး Web Service တည်ဆောက်မယ်။
3. Render က မေးတဲ့ Environment Variables ထဲမှာ အောက်ပါအချက်တွေ ထည့်ပါ။
   - `SUPABASE_URL` = Supabase Project URL
   - `SUPABASE_SECRET_KEY` = Supabase `sb_secret_...` Secret key (သို့) Legacy `service_role` key
   - `APP_PASSWORD` = မောင့် Recap App ကို Login ဝင်မယ့် ကိုယ်ပိုင် password (ရှည်ရှည်ထားပါ)
   - `JWT_SECRET` = Render က generated value ဖန်တီးပေးထားပါက အဲဒီအတိုင်းထားပါ
   - `WORKER_TOKEN` = Render က generated value ဖန်တီးပေးထားပါက အဲဒီအတိုင်းထားပါ
4. Deploy ပြီးရင် Render မှာ `https://...onrender.com` ပုံစံ Service URL ရမယ်။ `/health` ကိုဖွင့်ပြီး `status: ok` ပြရပါမယ်။ `needs_setup` ပြရင် Environment Variables မပြည့်သေးပါ။

## အဆင့် 4 — Google Gemini API Key

1. https://aistudio.google.com/apikey ကိုဖွင့်ပါ။
2. API Key တစ်ခုဖန်တီးပါ။
3. ဒီ Key ကို Lovable ထဲ မထည့်ပါနှင့်။ Colab Notebook မှာသာ private input အဖြစ် ထည့်ပါ။
4. `GEMINI_MODEL` ကို `gemini-3.8-flash`, `GEMINI_TTS_MODEL` ကို `gemini-3.8-flash-tts` သုံးထားပါတယ်။ Gemini 3.8 Flash TTS မှာ Burmese language ကို support လုပ်တယ်လို့ Google docs မှာ ဖော်ပြထားပါတယ်။ Free quota က model/project/region အလိုက် ကန့်သတ်ချက်ရှိနိုင်ပါတယ်။

## အဆင့် 5 — Colab Worker စတင်ရန်

1. https://colab.research.google.com/ ကိုဖွင့်ပါ။
2. **File → Upload notebook** ကိုရွေးပြီး ZIP ထဲက `colab_worker.ipynb` ကို upload လုပ်ပါ။
3. Notebook ရဲ့ Cell 1 ကို Run လုပ်ပြီး FFmpeg, Myanmar font, Python packages တပ်ပါ။
4. Cell 2 ကို Run လုပ်ပြီး Google Account နဲ့ Sign in လုပ်ပါ။ **Source Video ရှိတဲ့ Drive Account နဲ့ တူရပါမယ်။**
5. Cell 3 ကို Run လုပ်ပြီး ZIP ထဲက `colab_worker.py` ကို ရွေး Upload လုပ်ပါ။
6. Cell 4 မှာ အောက်ပါအချက်တွေ ထည့်ပါ။
   - Render API Base URL = `https://your-service.onrender.com` (နောက်ဆုံး slash မထည့်ပါနှင့်)
   - Render `WORKER_TOKEN`
   - Gemini API Key
7. Cell 5 ကို Run လုပ်ထားပါ။ `Colab Worker စတင်ပါပြီ` လို့ပြရင် Worker စောင့်နေပါပြီ။ Notebook ကို မပိတ်ပါနှင့်။

## အဆင့် 6 — Lovable Frontend ဖန်တီးရန်

1. https://lovable.dev/ ကိုဖွင့်ပါ။
2. New Project ဖန်တီးပါ။
3. `LOVABLE_PROMPT_MY.md` ဖိုင်ထဲက Prompt အားလုံးကို Copy လုပ်ပြီး Lovable Chat ထဲ Paste လုပ်ပါ။
4. Lovable က App တည်ဆောက်ပြီးလျှင် Settings မှာ Render API Base URL ကို ထည့်ပါ။
5. App Login Password က Render ထဲမှာ `APP_PASSWORD` သတ်မှတ်ထားတဲ့ password ဖြစ်ပါတယ်။

## အလုပ်လုပ်ပုံ

1. Video ကို Google Drive ထဲ Upload လုပ်ပါ။ File ကို Private/Restricted ထားပါ။ Colab မှာ Sign in ဝင်ထားတဲ့ Google Account က အဲဒီ file ကို ဖွင့်ခွင့်ရှိရပါမယ်။
2. Drive share link ကို Lovable App > New Recap မှာ paste လုပ်ပါ။ App က File ID ကို backend ပို့ပေးမယ်။
3. Script language, output minutes, Channel Name/Watermark, Subtitle color/outline/font/position, Voice, optional background music ကို ရွေးပါ။
4. Worker က Video ကို ၈ မိနစ်စီ proxy clip ခွဲပြီး Gemini နဲ့ အပိုင်းလိုက်သုံးသပ်မယ်။ Script ထွက်လာရင် Job အခြေအနေ `ဇာတ်ညွှန်းစစ်ဆေးရန်` ဖြစ်မယ်။
5. Lovable မှာ Script ကို ဖတ်၊ ပြင်၊ Subtitle/Watermark settings ပြင်ပြီး **Approve & Render** နှိပ်ပါ။
6. Colab Worker က Burmese Voice ထုတ်၊ Voice ကို Whisper နဲ့ပြန်ဖတ်ပြီး Subtitle timestamp ရယူ၊ AI highlight Scene များကို montage လုပ်၊ watermark/subtitle burn-in, optional BGM mix လုပ်ပြီး 1080p MP4 အဖြစ် Google Drive ထဲတင်မယ်။
7. ပြီးသွားရင် Lovable Job Detail မှာ Google Drive Result Link ပေါ်မယ်။

## အရေးကြီးသော သတိပြုရန်

- Colab Worker မ run နေရင် Job တွေ `queued` သို့မဟုတ် `approved` အဖြစ် စောင့်နေပါမယ်။
- Colab Runtime ၁၂ နာရီအထိ ရနိုင်တယ်ဆိုတာ အာမခံမဟုတ်ပါ။ Resource, free usage, idle policy ပြောင်းနိုင်ပါတယ်။ Runtime ရပ်သွားရင် Notebook ကို ပြန်ဖွင့်၊ Cell-2 မှ re-authenticate, `colab_worker.py` ပြန် upload, Cell-4 secrets ပြန်ထည့်ပြီး Cell-5 run လုပ်ပါ။
- ၂–၃ နာရီ Video processing က quota/time အများကြီးလိုနိုင်ပါတယ်။ Google API rate limit ကျော်ရင် retry လုပ်မယ်၊ အလွန်ကြာလျှင် အဲဒီ Job ကို Failed ပြနိုင်ပါတယ်။
- Google Drive link ကို Public မဖွင့်ပါနှင့်။ Restricted ဖြစ်နေပြီး Colab မှာ အဲဒီ account နဲ့ ဝင်ထားလျှင် ရပါတယ်။
- အရင်ဆုံး ကိုယ်ပိုင် ၂–၅ မိနစ် test video နဲ့ စမ်းပါ။ အားလုံးအဆင်ပြေမှ ၂–၃ နာရီဗီဒီယိုကို run ပါ။

## Troubleshooting

- **`needs_setup`** — Render Environment Variables မပြည့်သေးပါ။ Supabase URL/key, APP_PASSWORD စစ်ပါ။
- **`Invalid worker token`** — Notebook မှာ ထည့်ထားတဲ့ WORKER_TOKEN နဲ့ Render Environment ထဲက value မတူပါ။
- **Drive 404/403** — File ID မှန်မမှန်၊ Colab မှာဝင်ထားတဲ့ Google Account က Drive file ကို ဖွင့်နိုင်မနိုင် စစ်ပါ။
- **Gemini 429/RESOURCE_EXHAUSTED** — Free API quota/rate limit ပြည့်သွားတာဖြစ်နိုင်တယ်။ နောက်မှ ထပ်ကြိုးစားပါ သို့မဟုတ် Google AI Studio Usage/Rate limits ကို စစ်ပါ။
- **Subtitle စာလုံးမှား** — မြန်မာ ASR အမှားဖြစ်နိုင်ပါတယ်။ Script ကို ပြင်နိုင်ပေမဲ့ ASR Subtitle ကို manual ပြန်စစ်ရန် လိုနိုင်ပါတယ်။
- **Colab disconnected** — Runtime ပြန်စပြီး Notebook Cell 2 မှ 5 အထိ ပြန် run ပါ။ Database ထဲသိမ်းထားတဲ့ analysis chunks တွေကို Worker က ဆက်သုံးနိုင်ဖို့ ပြင်ဆင်ထားပါတယ်။
