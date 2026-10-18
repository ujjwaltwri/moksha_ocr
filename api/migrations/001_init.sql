-- Moksha entry system: day-1 schema.
create extension if not exists citext;
create extension if not exists pgcrypto;

create type reg_status as enum ('pending', 'processing', 'approved', 'review', 'rejected');

create table colleges (
  id serial primary key,
  slug text not null unique,           -- template file name, e.g. "nsut"
  name text not null,
  aliases text[] not null default '{}',
  email_domains text[] not null default '{}',
  roll_regex text,                     -- null = no rule yet
  template jsonb,                      -- labels, validity rule, etc.
  allowed boolean not null default true
);

create table registrations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  college_id int references colleges,
  college_other text,                  -- set when the student picked "Other"
  roll_no text not null,               -- normalised: uppercase, no spaces or dashes
  course text,
  email citext not null unique,
  college_email boolean not null default false,  -- email domain belongs to the chosen college
  phone text,
  id_image_key text not null,
  photo_crop_key text,                 -- face cropped from the card, shown at the gate
  image_phash bigint,                  -- perceptual hash for duplicate cards
  status reg_status not null default 'pending',
  ocr jsonb,                           -- extracted fields + confidences
  reasons text[] not null default '{}',
  consent_entry boolean not null,
  consent_dataset boolean not null default false,
  consent_version text not null,
  status_token text not null unique,
  client_ip inet,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint consent_entry_given check (consent_entry),
  constraint college_chosen check (college_id is not null or college_other is not null)
);

-- Only one live registration per college + roll number.
create unique index one_active_roll on registrations (college_id, lower(roll_no))
  where status in ('pending', 'processing', 'approved');
create index registrations_status on registrations (status, created_at);

create table review_actions (
  id bigserial primary key,
  registration_id uuid not null references registrations,
  reviewer text not null,
  decision reg_status not null,
  reason text,
  corrections jsonb,
  created_at timestamptz not null default now()
);

create table passes (
  id uuid primary key default gen_random_uuid(),
  registration_id uuid unique references registrations,
  issued_at timestamptz not null default now(),
  email_sent_at timestamptz,
  revoked boolean not null default false
);

create table checkins (
  id bigserial primary key,
  pass_id uuid not null references passes,
  device_id text not null,
  gate text,
  scanned_at timestamptz not null,     -- time on the phone
  synced_at timestamptz not null default now(),
  result text not null                 -- admitted / denied / duplicate
);

create table audit_log (
  id bigserial primary key,
  actor text,
  action text not null,
  target uuid,
  detail jsonb,
  at timestamptz not null default now()
);
