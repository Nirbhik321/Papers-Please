-- Keep the Render free-tier API awake, and keep the cron history small.
--
-- Render puts a free web service to sleep after 15 minutes without traffic.
-- Pinging /healthz every 6 minutes means it never sleeps (cron works in whole
-- minutes, so 6 min stands in for 6½). /healthz doesn't touch the database.
--
-- BEFORE RUNNING: replace YOUR-SERVICE with your Render service's hostname.

create extension if not exists pg_cron;
create extension if not exists pg_net with schema extensions;

-- Re-running this file replaces the jobs instead of duplicating them
select cron.unschedule(jobid) from cron.job
 where jobname in ('keep-render-awake', 'clear-cron-history');

-- Job 1: ping the API every 6 minutes
select cron.schedule(
  'keep-render-awake',
  '*/6 * * * *',
  $$ select net.http_get(url := 'https://YOUR-SERVICE.onrender.com/healthz', timeout_milliseconds := 10000); $$
);

-- Job 2: every 3 days at 03:00 UTC, clear cron run history (keeps the last day
-- so you can still check the pings are working). pg_net deletes its own stored
-- responses after 6 hours, so nothing else accumulates.
select cron.schedule(
  'clear-cron-history',
  '0 3 */3 * *',
  $$ delete from cron.job_run_details where end_time < now() - interval '1 day'; $$
);
