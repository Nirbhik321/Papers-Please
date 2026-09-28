-- Papers Please — database schema (mirrors server/db.py)
--
-- Row-level security is ON for every table with NO policies: Supabase's public
-- REST API (anon / authenticated keys) can't read or write anything. Only the
-- API server, connecting as the database owner via DATABASE_URL, can.

create table if not exists papers (
  id                 serial primary key,
  status             varchar(24) not null default 'processing',
  stage              varchar(24) not null default 'queued',
  status_reason      text,
  subject_code       varchar(16),
  subject_name       varchar(200),
  exam_year          integer,
  exam_month         varchar(16),
  paper_type         varchar(16) not null default 'see',
  session_key        varchar(64),
  detected           text,
  filename           varchar(255) not null,
  content_hash       varchar(64) not null unique,
  storage_key        varchar(255) not null,
  pdf_type           varchar(16),
  page_count         integer,
  question_count     integer,
  modules_found      integer,
  upload_token_hash  varchar(64) not null,
  uploader_hash      varchar(64),
  reviewed_by        varchar(255),
  reviewed_at        timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

-- One live paper per exam session (e.g. BCS502 January 2025)
create unique index if not exists uq_papers_live_session
  on papers (session_key) where status = 'approved';
create index if not exists ix_papers_subject_status on papers (subject_code, status);

create table if not exists sub_questions (
  id              serial primary key,
  paper_id        integer not null references papers(id) on delete cascade,
  module_no       integer not null,
  q_no            integer not null,
  sub_q           varchar(4) not null,
  is_or_alt       integer not null default 0,
  text            text not null,
  marks           integer,
  bloom_level     varchar(4),
  course_outcome  varchar(8)
);
create index if not exists ix_sub_questions_paper_id on sub_questions (paper_id);

create table if not exists topics (
  id                   serial primary key,
  subject_code         varchar(16) not null,
  module_no            integer not null,
  stable_key           varchar(16) not null,
  label                varchar(120),
  representative_text  text not null,
  avg_marks            double precision,
  frequency            integer not null default 0,
  weighted_score       double precision not null default 0,
  last_seen_year       integer
);
create index if not exists ix_topics_subject_module on topics (subject_code, module_no);

create table if not exists topic_appearances (
  topic_id         integer not null references topics(id) on delete cascade,
  sub_question_id  integer not null references sub_questions(id) on delete cascade,
  primary key (topic_id, sub_question_id)
);

create table if not exists subject_snapshots (
  subject_code    varchar(16) primary key,
  subject_name    varchar(200) not null,
  paper_count     integer not null,
  topic_count     integer not null,
  min_year        integer,
  max_year        integer,
  data            text not null,
  cheatsheet_pdf  bytea,
  questions_csv   text,
  updated_at      timestamptz not null default now()
);

create table if not exists blocked_uploaders (
  uploader_hash  varchar(64) primary key,
  reason         text,
  blocked_by     varchar(255),
  created_at     timestamptz not null default now()
);

alter table papers             enable row level security;
alter table sub_questions      enable row level security;
alter table topics             enable row level security;
alter table topic_appearances  enable row level security;
alter table subject_snapshots  enable row level security;
alter table blocked_uploaders  enable row level security;

-- Private bucket for original uploads (never public; only the server's service key reads it)
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('uploads', 'uploads', false, 10485760, array['application/pdf'])
on conflict (id) do nothing;
