-- Firm key v2 (Nov 2026): also ignore spaces, hyphens and "&" vs "AND", so name variants of one firm
-- ("GUANG DONG"/"GUANGDONG", "M & C"/"M AND C", "BIO-TECH"/"BIOTECH") merge into one admin row.
-- Same rule in pipeline/firms.py firm_key() and the site's firmKey(). Apply together with that code.
create or replace function public.firm_key(t text) returns text
language sql immutable parallel safe set search_path to 'public' as $function$
  select regexp_replace(replace(btrim(regexp_replace(
    regexp_replace(regexp_replace(regexp_replace(
      regexp_replace(upper(coalesce(t, '')), '[.,()（）"“”''’]', ' ', 'g'),
      '\mCOMPANY\M', 'CO', 'g'), '\mLIMITED\M', 'LTD', 'g'), '\mCORPORATION\M', 'CORP', 'g'),
    '\s+', ' ', 'g')), '&', ' AND '), '[[:space:]\-‐–—_/\\·•+:;!?#*~|]', '', 'g')
$function$;

-- stored keys move to the new form (checked beforehand: no two stored keys collide)
update firm_zh set firm_key = firm_key(firm_key) where firm_key <> firm_key(firm_key);
update firm_ai set firm_key = firm_key(firm_key) where firm_key <> firm_key(firm_key);

refresh materialized view firm_all_mv;
