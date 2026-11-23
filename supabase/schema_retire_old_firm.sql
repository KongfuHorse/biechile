-- The old FDA-only firm page (FEI based) is replaced by admin_firms2 / admin_save_firm2 / admin_delete_firm2.
-- A cached copy of the old admin page would still save into firm_names, which the new page does not show,
-- so the old functions now stop with a message asking the user to reload.
create or replace function admin_firms(p_token text, p_limit int default 200)
returns jsonb language plpgsql security definer set search_path = public as $$
begin raise exception '后台已更新，请按 Cmd+Shift+R（Windows 按 Ctrl+F5）刷新页面后再用'; end $$;

create or replace function admin_save_firm(p_token text, p_fei text, p_firm_en text, p_zh text,
                                           p_credit_code text, p_source_url text, p_note text)
returns void language plpgsql security definer set search_path = public as $$
begin raise exception '后台已更新，请按 Cmd+Shift+R（Windows 按 Ctrl+F5）刷新页面后再保存'; end $$;

create or replace function admin_delete_firm(p_token text, p_fei text)
returns void language plpgsql security definer set search_path = public as $$
begin raise exception '后台已更新，请按 Cmd+Shift+R（Windows 按 Ctrl+F5）刷新页面后再操作'; end $$;
