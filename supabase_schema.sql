-- Burmese Recap Studio: run this entire file once in Supabase SQL Editor.
-- Videos/audio are NOT stored in this database. Only job metadata and the editable script are stored.

create extension if not exists pgcrypto;

create table if not exists public.recap_jobs (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    source_drive_file_id text not null,
    source_filename text not null,
    movie_title text not null default '',
    status text not null default 'queued'
        check (status in ('queued','processing','awaiting_approval','approved','completed','failed')),
    progress integer not null default 0 check (progress >= 0 and progress <= 100),
    stage text not null default 'queued',
    message text not null default '',
    settings jsonb not null default '{}'::jsonb,
    analysis_json jsonb not null default '{"chunks": []}'::jsonb,
    highlights_json jsonb not null default '[]'::jsonb,
    script_text text,
    worker_id text,
    locked_at timestamptz,
    result_drive_file_id text,
    result_filename text,
    result_url text,
    error_message text
);

create index if not exists recap_jobs_status_created_idx
    on public.recap_jobs (status, created_at asc);
create index if not exists recap_jobs_updated_idx
    on public.recap_jobs (updated_at asc);

create or replace function public.set_recap_jobs_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists recap_jobs_updated_at_trigger on public.recap_jobs;
create trigger recap_jobs_updated_at_trigger
before update on public.recap_jobs
for each row execute function public.set_recap_jobs_updated_at();

-- One Colab worker claims the next queued or approved job. A job left in
-- 'processing' for 20+ minutes can be reclaimed after a Colab disconnect.
-- Partial analysis chunks are retained in analysis_json, so analysis can resume.
create or replace function public.claim_recap_job(p_worker_id text)
returns setof public.recap_jobs
language plpgsql
security definer
set search_path = public
as $$
declare
    selected_id uuid;
begin
    select id into selected_id
    from public.recap_jobs
    where status in ('queued', 'approved')
       or (status = 'processing' and updated_at < now() - interval '20 minutes')
    order by
        case when status = 'approved' then 0 else 1 end,
        created_at asc
    limit 1
    for update skip locked;

    if selected_id is null then
        return;
    end if;

    update public.recap_jobs
    set status = 'processing',
        worker_id = p_worker_id,
        locked_at = now(),
        stage = case when coalesce(script_text, '') <> '' then 'rendering' else 'analyzing' end,
        message = case when coalesce(script_text, '') <> '' then 'အတည်ပြုထားသော Script ကို Video အဖြစ် Render လုပ်နေပါတယ်။' else 'Video ကို အပိုင်းလိုက် AI သုံးသပ်နေပါတယ်။' end
    where id = selected_id;

    return query select * from public.recap_jobs where id = selected_id;
end;
$$;

-- The API uses the Supabase Secret key (or legacy service_role JWT) only on the server.
-- No browser client is allowed to read/write this table directly.
alter table public.recap_jobs enable row level security;
revoke all on public.recap_jobs from anon, authenticated;
grant all on public.recap_jobs to service_role;
revoke all on function public.claim_recap_job(text) from public, anon, authenticated;
grant execute on function public.claim_recap_job(text) to service_role;

notify pgrst, 'reload schema';
