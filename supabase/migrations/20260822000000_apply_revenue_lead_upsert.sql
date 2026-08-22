-- Phase 5 (AUTH-1): canonical lead write primitive for AION Revenue Factory.
-- Additive, reversible (DROP FUNCTION to remove). Writes ONLY revenue_leads +
-- revenue_sync_events; never opportunities/deals. SECURITY DEFINER so it honors
-- the RLS boundary (default-deny) through one audited entry point. Version is
-- derived from the outbox (revenue_* has no row version column), so no schema
-- change to revenue_leads is required (AUTH-4 not needed for this primitive).
--
-- Deployed to project qbahthzqvxytfgobgtxa on 2026-08-22 (migration
-- phase5_apply_revenue_lead_upsert) and validated by a synthetic production
-- canary; see docs/PHASE5_CANARY_RESULTS.md.
create or replace function public.apply_revenue_lead_upsert(
  p_row jsonb,
  p_idempotency_key text,
  p_actor_type text default 'system',
  p_actor_id text default 'aion_revenue_factory',
  p_expected_version bigint default null
) returns jsonb
  language plpgsql
  security definer
  set search_path to 'public'
as $function$
declare
  v_event   public.revenue_sync_events%rowtype;
  v_lead_id text := p_row->>'lead_id';
  v_urid    text := p_row->>'universal_record_id';
  v_source  text := coalesce(p_row->>'source_system', 'aion_revenue_factory');
  v_prev    bigint;
  v_next    bigint;
  v_uuid    text;
begin
  if v_lead_id is null or v_urid is null then
    raise exception 'lead_id and universal_record_id are required';
  end if;

  -- idempotency: replay returns the original result, no new state
  select * into v_event from public.revenue_sync_events
    where idempotency_key = p_idempotency_key;
  if found then
    return jsonb_build_object('event_id', v_event.event_id,
      'new_version', v_event.new_version, 'duplicate', true, 'lead_id', v_lead_id);
  end if;

  -- current version derived from the outbox (no row-level version column)
  select coalesce(max(new_version), 0) into v_prev
    from public.revenue_sync_events
    where entity_type = 'lead' and entity_id = v_lead_id;

  if p_expected_version is not null and p_expected_version <> v_prev then
    raise exception 'version conflict: expected %, current %', p_expected_version, v_prev
      using errcode = '40001';
  end if;
  v_next := v_prev + 1;

  -- upsert the canonical lead (system owns id / created_at / updated_at)
  insert into public.revenue_leads as l (
    universal_record_id, source_record_id, lead_id, full_name, email, role,
    company, website, industry, country, lead_score, buying_intent,
    suggested_price, status, airtable_record_id, raw_metadata, source_system
  ) values (
    v_urid,
    p_row->>'source_record_id',
    v_lead_id,
    p_row->>'full_name',
    p_row->>'email',
    p_row->>'role',
    p_row->>'company',
    p_row->>'website',
    p_row->>'industry',
    p_row->>'country',
    nullif(p_row->>'lead_score','')::numeric,
    p_row->>'buying_intent',
    nullif(p_row->>'suggested_price','')::numeric,
    coalesce(p_row->>'status', 'New'),
    p_row->>'airtable_record_id',
    coalesce(p_row->'raw_metadata', '{}'::jsonb),
    v_source
  )
  on conflict (lead_id) do update set
    full_name       = excluded.full_name,
    email           = excluded.email,
    role            = excluded.role,
    company         = excluded.company,
    website         = excluded.website,
    industry        = excluded.industry,
    country         = excluded.country,
    lead_score      = excluded.lead_score,
    buying_intent   = excluded.buying_intent,
    suggested_price = excluded.suggested_price,
    status          = excluded.status,
    raw_metadata    = excluded.raw_metadata,
    source_system   = excluded.source_system,
    updated_at      = now()
  returning l.id into v_uuid;

  -- emit the outbox event (previous/new_version satisfy the NOT NULL contract)
  insert into public.revenue_sync_events (
    entity_type, entity_id, source_system, event_type, payload,
    previous_version, new_version, actor_type, actor_id,
    airtable_record_id, supabase_record_id, idempotency_key
  ) values (
    'lead', v_lead_id, v_source,
    case when v_prev = 0 then 'lead.created' else 'lead.updated' end,
    p_row, v_prev, v_next, p_actor_type, p_actor_id,
    p_row->>'airtable_record_id', v_uuid, p_idempotency_key
  ) returning * into v_event;

  return jsonb_build_object('event_id', v_event.event_id, 'new_version', v_next,
    'duplicate', false, 'lead_id', v_lead_id, 'supabase_id', v_uuid);
end;
$function$;
