<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: signing-in-is-connecting -->
<!-- Release title: Signing In Is Connecting -->
<!-- Source range: c7b49fb..6384171 (restored: this release describes the sign-in fix only) -->

# Technical Release Notes

- Sign-in read the Wikimedia global account id from official Toolhub's `/api/user/`. That endpoint is served by the `CurrentUser` serializer, whose published schema is `casl, csrf_token, email, id, is_anonymous, is_authenticated, username` -- it carries no `social_auth` at all. The extraction therefore returned `""` on every login this codebase has ever performed, and `users.wikimedia_global_user_id` was never written at sign-in. Only `/api/users/<id>/`, the `UserDetail` serializer, exposes it, so `oauth_callback` now asks for that row when the sign-in profile has none.
- The column was filled only out of band, by the reconciliation pass copying it from the Toolhub account projection. Between a first sign-in and the next pass an account was fully authenticated and had no Wikimedia identity, which is precisely the window the digest endpoint refused: eight HTTP 400s in production between 00:56 and 01:06 UTC, each a 59-byte body carrying that message.
- A failed lookup logs and returns empty rather than failing the sign-in. Identity is not authentication -- the token exchange already succeeded, and the reconciliation pass remains the backstop it always was. Sessions that predate this fix never revisit identity, so `subscriptions_post` adopts the id from the account projection through the new `identity_graph.hydrate_user_identity` before refusing, and writes only when the value actually changes.
- The existing test could not have caught this: its fake returned `social_auth` from `/api/user/`, so it agreed with the code under test rather than with Toolhub. The fake now answers per URL as the real API does, which makes it fail without the login change. Verified against the live API and the deployed database before the fix was written.
