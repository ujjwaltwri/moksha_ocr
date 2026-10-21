-- Day 3-4: passes, gate sync, devices, staff tokens, review claims.

-- ---------- Staff (reviewers and admins) ----------
-- Tokens are random strings handed to each person; only their SHA-256 is stored.
create table staff (
  id serial primary key,
  name text not null,
  role text not null check (role in ('reviewer', 'admin')),
  token_hash text not null unique,
  revoked boolean not null default false,
  created_at timestamptz not null default now()
);

-- ---------- Gate devices ----------
create table devices (
  id serial primary key,
  gate text not null,
  token_hash text not null unique,
  revoked boolean not null default false,
  created_at timestamptz not null default now(),
  last_seen_at timestamptz
);

-- ---------- Review claims ----------
alter table registrations
  add column claimed_by int references staff,
  add column claimed_at timestamptz;
create index registrations_review_queue on registrations (created_at) where status = 'review';

-- ---------- Passes ----------
-- seq increases on every insert or change, so gates can download only what changed.
create sequence manifest_seq;
alter table passes
  add column token text,                 -- the signed QR content
  add column thumb bytea,                -- 160x160 WebP face crop for the gate screen
  add column days int[] not null default '{1,2,3}',
  add column seq bigint not null default nextval('manifest_seq'),
  add column email_attempts int not null default 0,
  add column email_error text,
  add column updated_at timestamptz not null default now();
create index passes_seq on passes (seq);

create function passes_bump_seq() returns trigger language plpgsql as $$
begin
  new.seq := nextval('manifest_seq');
  new.updated_at := now();
  return new;
end $$;
create trigger passes_bump_seq before update of revoked, token, thumb, days on passes
  for each row execute function passes_bump_seq();

-- ---------- Check-ins from gate phones ----------
-- The app makes the id (a UUID) and retries until the server accepts it, so the id is the key.
-- pass_id is plain text: a phone also records scans of passes that aren't in its list.
drop table checkins;
create table checkins (
  seq bigserial primary key,             -- sync cursor for other gates
  id text not null unique,               -- the phone's check-in id
  pass_id text not null,
  device_id text not null,
  device int references devices,
  gate text,
  day int not null,
  result text not null check (result in ('admitted', 'denied', 'duplicate')),
  reason text,
  scanned_at timestamptz not null,       -- time on the phone
  synced_at timestamptz not null default now(),
  conflict boolean not null default false -- admitted after another gate had already admitted it
);
create index checkins_pass_day on checkins (pass_id, day) where result = 'admitted';
