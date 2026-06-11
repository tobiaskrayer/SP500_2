-- ============================================================
--  Row-Level-Security für das Portfolio (lots, realized_trades)
--
--  Warum: Der SUPABASE_ANON_KEY ist konstruktionsbedingt öffentlich
--  (steckt in jeder Browser-Session). Die App filtert zwar überall
--  klientseitig nach user_id, aber NUR diese Policies erzwingen die
--  Trennung serverseitig — ohne sie kann jeder registrierte Nutzer
--  per direktem REST-Call fremde Portfolios lesen und ändern.
--
--  Anwenden: Supabase-Dashboard -> SQL Editor -> Inhalt einfügen -> Run.
--  Das Skript ist idempotent (mehrfaches Ausführen ist harmlos).
--
--  Hinweis: Geht davon aus, dass user_id den Typ uuid hat (Standard).
--  Falls die Spalte als text angelegt wurde, in allen Policies
--  "(select auth.uid())" durch "(select auth.uid())::text" ersetzen.
-- ============================================================

-- RLS aktivieren (blockiert ab sofort alles, was keine Policy erlaubt)
alter table public.lots enable row level security;
alter table public.realized_trades enable row level security;

-- ── lots ─────────────────────────────────────────────────────
drop policy if exists "lots_select_own" on public.lots;
create policy "lots_select_own" on public.lots
  for select to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "lots_insert_own" on public.lots;
create policy "lots_insert_own" on public.lots
  for insert to authenticated
  with check ((select auth.uid()) = user_id);

drop policy if exists "lots_update_own" on public.lots;
create policy "lots_update_own" on public.lots
  for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "lots_delete_own" on public.lots;
create policy "lots_delete_own" on public.lots
  for delete to authenticated
  using ((select auth.uid()) = user_id);

-- ── realized_trades ──────────────────────────────────────────
drop policy if exists "trades_select_own" on public.realized_trades;
create policy "trades_select_own" on public.realized_trades
  for select to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "trades_insert_own" on public.realized_trades;
create policy "trades_insert_own" on public.realized_trades
  for insert to authenticated
  with check ((select auth.uid()) = user_id);

drop policy if exists "trades_update_own" on public.realized_trades;
create policy "trades_update_own" on public.realized_trades
  for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "trades_delete_own" on public.realized_trades;
create policy "trades_delete_own" on public.realized_trades
  for delete to authenticated
  using ((select auth.uid()) = user_id);

-- Kontrolle: beide Tabellen müssen rowsecurity = true zeigen
select tablename, rowsecurity
from pg_tables
where schemaname = 'public' and tablename in ('lots', 'realized_trades');
