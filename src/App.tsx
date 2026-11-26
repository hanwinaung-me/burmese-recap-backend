
import { useEffect, useRef, useState } from "react";

const API = "https://burmese-recap-api.onrender.com";

type Job = {
  id: string;
  source_filename: string;
  movie_title: string;
  status: string;
  progress: number;
  stage: string;
  message: string;
  script_text?: string;
  result_url?: string;
  error_message?: string;
};

export default function App() {
  const [token, setToken] = useState(localStorage.getItem("recap_token") || "");
  const [password, setPassword] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [minutes, setMinutes] = useState(12);
  const [channel, setChannel] = useState("Burmese Recap");
  const [rights, setRights] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [script, setScript] = useState("");
  const [error, setError] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  async function request(path: string, method = "GET", body?: any) {
    const res = await fetch(API + path, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body ? { "Content-Type": "application/json" } : {})
      },
      body: body ? JSON.stringify(body) : undefined
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Request failed");
    return data;
  }

  async function login() {
    try {
      setError("");
      const res = await fetch(API + "/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Login မအောင်မြင်ပါ");
      localStorage.setItem("recap_token", data.access_token);
      setToken(data.access_token);
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function loadJobs() {
    try {
      const data = await request("/api/jobs");
      setJobs(data.jobs || []);
    } catch (e: any) {
      setError(e.message);
    }
  }

  useEffect(() => {
    if (!token) return;
    loadJobs();
  }, [token]);

  useEffect(() => {
    if (!job?.id) return;
    if (timer.current) clearInterval(timer.current);

    timer.current = setInterval(async () => {
      try {
        const data = await request(`/api/jobs/${job.id}`);
        setJob(data);
        if (data.script_text) setScript(data.script_text);
        if (["completed", "failed", "awaiting_approval"].includes(data.status)) {
          if (timer.current) clearInterval(timer.current);
          loadJobs();
        }
      } catch {}
    }, 5000);

    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [job?.id]);

  function uploadVideo() {
    if (!file || !rights) return;
    setUploading(true);
    setUploadProgress(0);
    setError("");

    const form = new FormData();
    form.append("video", file);
    form.append("movie_title", title || file.name);
    form.append("target_minutes", String(minutes));
    form.append("channel_name", channel);
    form.append("rights_confirmed", "true");

    const xhr = new XMLHttpRequest();
    xhr.open("POST", API + "/api/jobs/upload");
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        setUploadProgress(Math.round(event.loaded / event.total * 100));
      }
    };

    xhr.onload = () => {
      setUploading(false);
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status < 200 || xhr.status >= 300) {
          throw new Error(data.detail || "Upload မအောင်မြင်ပါ");
        }
        setJob(data);
        loadJobs();
      } catch (e: any) {
        setError(e.message);
      }
    };

    xhr.onerror = () => {
      setUploading(false);
      setError("အင်တာနက်ချိတ်ဆက်မှု မအောင်မြင်ပါ");
    };

    xhr.send(form);
  }

  async function saveScript() {
    if (!job) return;
    try {
      const data = await request(`/api/jobs/${job.id}/script`, "PATCH", {
        script_text: script
      });
      setJob(data);
      alert("Script သိမ်းပြီးပါပြီ");
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function approve() {
    if (!job) return;
    try {
      const data = await request(`/api/jobs/${job.id}/approve`, "POST");
      setJob(data);
      loadJobs();
    } catch (e: any) {
      setError(e.message);
    }
  }

  function logout() {
    localStorage.removeItem("recap_token");
    setToken("");
    setJob(null);
  }

  if (!token) {
    return (
      <main className="min-h-screen bg-[#090d18] text-white flex items-center justify-center p-5">
        <div className="w-full max-w-sm bg-[#151c2d] p-7 rounded-2xl">
          <h1 className="text-3xl font-bold text-center">RECAP STUDIO</h1>
          <p className="text-center text-gray-400 mt-2">မြန်မာ AI Video Recap</p>
          <input
            className="w-full p-4 mt-7 rounded-xl bg-[#0c1322]"
            type="password"
            placeholder="Password"
            value={password}
            onChange={e => setPassword(e.target.value)}
          />
          <button onClick={login} className="w-full mt-4 p-4 rounded-xl bg-blue-600 font-bold">
            Login
          </button>
          {error && <p className="text-red-400 mt-3">{error}</p>}
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#090d18] text-white p-4 md:p-8">
      <header className="max-w-5xl mx-auto flex justify-between items-center mb-8">
        <div>
          <h1 className="text-2xl font-bold">RECAP STUDIO</h1>
          <p className="text-gray-400 text-sm">Burmese AI Video Production</p>
        </div>
        <button onClick={logout} className="px-4 py-2 bg-[#202a40] rounded-lg">
          Logout
        </button>
      </header>

      <div className="max-w-5xl mx-auto grid gap-5">
        <section className="bg-[#151c2d] p-5 rounded-2xl">
          <h2 className="text-xl font-bold mb-4">Video အသစ်ဖန်တီးမယ်</h2>

          <label className="block border-2 border-dashed border-blue-500 rounded-2xl p-7 text-center cursor-pointer">
            <div className="text-4xl mb-3">＋</div>
            <strong>ဖုန်းထဲက Video ရွေးပါ</strong>
            <p className="text-gray-400 text-sm mt-2">MP4, MOV, MKV, WEBM</p>
            <input
              type="file"
              accept="video/*"
              className="hidden"
              onChange={e => setFile(e.target.files?.[0] || null)}
            />
          </label>

          {file && (
            <div className="mt-4 p-3 bg-[#0c1322] rounded-xl">
              <p className="font-medium break-all">{file.name}</p>
              <p className="text-sm text-gray-400">
                {(file.size / 1024 / 1024).toFixed(1)} MB
              </p>
            </div>
          )}

          <input
            className="w-full mt-4 p-3 rounded-xl bg-[#0c1322]"
            placeholder="ဇာတ်ကားအမည်"
            value={title}
            onChange={e => setTitle(e.target.value)}
          />

          <label className="block mt-4 text-sm text-gray-300">Recap ကြာချိန်</label>
          <select
            className="w-full mt-2 p-3 rounded-xl bg-[#0c1322]"
            value={minutes}
            onChange={e => setMinutes(Number(e.target.value))}
          >
            {[5, 8, 10, 12, 15, 20, 25, 30].map(n =>
              <option key={n} value={n}>{n} မိနစ်</option>
            )}
          </select>

          <input
            className="w-full mt-4 p-3 rounded-xl bg-[#0c1322]"
            value={channel}
            onChange={e => setChannel(e.target.value)}
            placeholder="Channel Name / Watermark"
          />

          <label className="flex gap-3 items-start mt-5 text-sm text-gray-300">
            <input
              type="checkbox"
              checked={rights}
              onChange={e => setRights(e.target.checked)}
              className="mt-1"
            />
            ဒီ Video ကို အသုံးပြုခွင့်ရှိကြောင်း အတည်ပြုပါတယ်။
          </label>

          <button
            disabled={!file || !rights || uploading}
            onClick={uploadVideo}
            className="w-full mt-5 p-4 rounded-xl bg-blue-600 font-bold disabled:opacity-40"
          >
            {uploading ? `Uploading ${uploadProgress}%` : "Video Upload & AI စတင်မယ်"}
          </button>

          {uploading && (
            <div className="mt-4 bg-[#0c1322] h-3 rounded-full overflow-hidden">
              <div className="h-full bg-blue-500" style={{ width: `${uploadProgress}%` }} />
            </div>
          )}
        </section>

        {error && (
          <div className="bg-red-950 text-red-300 p-4 rounded-xl">{error}</div>
        )}

        {job && (
          <section className="bg-[#151c2d] p-5 rounded-2xl">
            <h2 className="text-xl font-bold">လုပ်ဆောင်မှု အခြေအနေ</h2>
            <p className="text-gray-300 mt-2">{job.message}</p>
            <div className="mt-4 h-3 bg-[#0c1322] rounded-full overflow-hidden">
              <div className="h-full bg-blue-500" style={{ width: `${job.progress}%` }} />
            </div>
            <p className="mt-2 text-sm text-gray-400">{job.progress}% · {job.stage}</p>

            {job.status === "awaiting_approval" && (
              <>
                <h3 className="font-bold mt-6 mb-2">မြန်မာ Recap Script</h3>
                <textarea
                  className="w-full min-h-72 p-4 rounded-xl bg-[#0c1322]"
                  value={script}
                  onChange={e => setScript(e.target.value)}
                />
                <button onClick={saveScript} className="w-full mt-3 p-3 bg-[#263650] rounded-xl">
                  Script သိမ်းမယ်
                </button>
                <button onClick={approve} className="w-full mt-3 p-4 bg-green-700 rounded-xl font-bold">
                  Approve & Video Edit စမယ်
                </button>
              </>
            )}

            {job.status === "completed" && job.result_url && (
              <a
                href={job.result_url}
                target="_blank"
                rel="noreferrer"
                className="block mt-5 p-4 text-center bg-green-700 rounded-xl font-bold"
              >
                Final MP4 ကြည့်ရန် / Download
              </a>
            )}

            {job.status === "failed" && (
              <p className="text-red-400 mt-4">{job.error_message || "လုပ်ဆောင်မှု မအောင်မြင်ပါ"}</p>
            )}
          </section>
        )}

        <section className="bg-[#151c2d] p-5 rounded-2xl">
          <div className="flex justify-between items-center">
            <h2 className="text-xl font-bold">အရင်လုပ်ထားသော Video များ</h2>
            <button onClick={loadJobs} className="text-blue-400">Refresh</button>
          </div>
          <div className="mt-4 grid gap-3">
            {jobs.map(item => (
              <button
                key={item.id}
                onClick={() => { setJob(item); setScript(item.script_text || ""); }}
                className="text-left p-4 bg-[#0c1322] rounded-xl"
              >
                <strong className="block break-all">{item.movie_title || item.source_filename}</strong>
                <span className="text-sm text-gray-400">{item.status} · {item.progress}%</span>
              </button>
            ))}
            {!jobs.length && <p className="text-gray-500">Video မရှိသေးပါ။</p>}
          </div>
        </section>
      </div>
    </main>
  );
}
