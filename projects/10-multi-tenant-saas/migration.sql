-- Apply to an explicitly selected Supabase test project. No production execution is implied.
begin;

create table if not exists public.tenants (
  id uuid primary key default gen_random_uuid(),
  name text not null
);
create table if not exists public.tenant_members (
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('admin','writer','reader','reviewer')),
  primary key (tenant_id,user_id)
);

-- SECURITY DEFINER avoids recursive membership RLS. Its result is always bound to
-- auth.uid(), takes no caller-supplied subject, and has a fixed search_path.
create or replace function public.has_tenant_role(target_tenant uuid, allowed_roles text[])
returns boolean language sql stable security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.tenant_members m
    where m.tenant_id = target_tenant and m.user_id = (select auth.uid())
      and m.role = any(allowed_roles)
  );
$$;
revoke all on function public.has_tenant_role(uuid,text[]) from public;
grant execute on function public.has_tenant_role(uuid,text[]) to authenticated;

create table if not exists public.tenant_resources (
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  id uuid not null default gen_random_uuid(),
  kind text not null check (kind in (
    'document','citation','conversation','cache','job','memory','checkpoint','export','vector','usage'
  )),
  data jsonb not null default '{}',
  version integer not null default 1 check (version>0),
  primary key (tenant_id,id)
);

alter table public.tenants enable row level security;
alter table public.tenant_members enable row level security;
alter table public.tenant_resources enable row level security;
alter table public.tenants force row level security;
alter table public.tenant_members force row level security;
alter table public.tenant_resources force row level security;

drop policy if exists tenant_read on public.tenants;
create policy tenant_read on public.tenants for select to authenticated
using (public.has_tenant_role(id,array['admin','writer','reader','reviewer']));

drop policy if exists membership_read on public.tenant_members;
create policy membership_read on public.tenant_members for select to authenticated
using (public.has_tenant_role(tenant_id,array['admin','writer','reader','reviewer']));
drop policy if exists membership_manage on public.tenant_members;
create policy membership_manage on public.tenant_members for all to authenticated
using (public.has_tenant_role(tenant_id,array['admin']))
with check (public.has_tenant_role(tenant_id,array['admin']));

drop policy if exists resource_read on public.tenant_resources;
create policy resource_read on public.tenant_resources for select to authenticated
using (public.has_tenant_role(tenant_id,array['admin','writer','reader','reviewer']));
drop policy if exists resource_write on public.tenant_resources;
create policy resource_write on public.tenant_resources for all to authenticated
using (public.has_tenant_role(tenant_id,array['admin','writer']))
with check (public.has_tenant_role(tenant_id,array['admin','writer']));

grant select on public.tenants to authenticated;
grant select,insert,update,delete on public.tenant_members,public.tenant_resources to authenticated;

insert into storage.buckets (id,name,public)
values ('tenant-documents','tenant-documents',false)
on conflict (id) do update set public=false;

create or replace function public.storage_tenant_id(object_name text)
returns uuid language sql immutable
set search_path = public, pg_temp
as $$
  select case
    when (storage.foldername(object_name))[1]
      ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
    then ((storage.foldername(object_name))[1])::uuid
    else null
  end;
$$;

drop policy if exists tenant_storage_read on storage.objects;
create policy tenant_storage_read on storage.objects for select to authenticated
using (
  bucket_id='tenant-documents'
  and public.has_tenant_role(public.storage_tenant_id(name),
                            array['admin','writer','reader','reviewer'])
);
drop policy if exists tenant_storage_write on storage.objects;
create policy tenant_storage_write on storage.objects for all to authenticated
using (
  bucket_id='tenant-documents'
  and public.has_tenant_role(public.storage_tenant_id(name),array['admin','writer'])
)
with check (
  bucket_id='tenant-documents'
  and public.has_tenant_role(public.storage_tenant_id(name),array['admin','writer'])
);
commit;

-- Bootstrap two real test users/tenants through reviewed admin SQL or a migration
-- operator. Application clients and workers use user JWTs, never the service key.
-- A database owner/service_role can bypass RLS despite FORCE; no claim otherwise.
