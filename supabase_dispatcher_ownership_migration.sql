alter table public.trips
    add column if not exists created_by uuid references auth.users(id) on delete set null;

alter table public.fuel_logs
    add column if not exists created_by uuid references auth.users(id) on delete set null;

alter table public.maintenance
    add column if not exists created_by uuid references auth.users(id) on delete set null;

alter table public.trips
    add column if not exists manifest_object_path text;

alter table public.fuel_logs
    add column if not exists invoice_object_path text;

create index if not exists trips_created_by_idx on public.trips(created_by);
create index if not exists fuel_logs_created_by_idx on public.fuel_logs(created_by);
create index if not exists maintenance_created_by_idx on public.maintenance(created_by);

select setval(
    pg_get_serial_sequence('public.trips', 'id'),
    coalesce(max(id), 1),
    max(id) is not null
)
from public.trips;

select setval(
    pg_get_serial_sequence('public.fuel_logs', 'id'),
    coalesce(max(id), 1),
    max(id) is not null
)
from public.fuel_logs;

select setval(
    pg_get_serial_sequence('public.maintenance', 'id'),
    coalesce(max(id), 1),
    max(id) is not null
)
from public.maintenance;

create or replace function public.prevent_record_owner_change()
returns trigger
language plpgsql
as $$
begin
    if new.created_by is distinct from old.created_by then
        raise exception 'Record ownership cannot be changed';
    end if;
    return new;
end;
$$;

drop trigger if exists trips_owner_immutable on public.trips;
create trigger trips_owner_immutable
    before update of created_by on public.trips
    for each row execute function public.prevent_record_owner_change();

drop trigger if exists fuel_logs_owner_immutable on public.fuel_logs;
create trigger fuel_logs_owner_immutable
    before update of created_by on public.fuel_logs
    for each row execute function public.prevent_record_owner_change();

drop trigger if exists maintenance_owner_immutable on public.maintenance;
create trigger maintenance_owner_immutable
    before update of created_by on public.maintenance
    for each row execute function public.prevent_record_owner_change();

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'fleet-trip-documents',
    'fleet-trip-documents',
    false,
    52428800,
    array['image/jpeg', 'image/png', 'image/webp']
)
on conflict (id) do update
set public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
