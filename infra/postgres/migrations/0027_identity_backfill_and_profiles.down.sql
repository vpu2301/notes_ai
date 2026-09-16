-- Reverse of 0027. The backfilled identities are deliberately NOT deleted:
-- by the time this could run, sessions, second factors and notes may hang
-- off them, and `users` still holds the same rows anyway — so removing the
-- function is the whole rollback.
DROP FUNCTION IF EXISTS public.profile_of_subs(uuid[]);
