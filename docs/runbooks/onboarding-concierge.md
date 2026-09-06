# Concierge onboarding (OPS-0)

**Who this is for:** whoever is watching the request-access inbox.
**SLA:** within one business hour, 08:00–20:00 Europe/Berlin.
**You need:** shell access to the auth-service host (or the ops job
runner). Nothing else — no Keycloak console, no database client.

Self-serve signup exists (`/auth/signup`), and this still exists beside
it. The first twenty or fifty users teach more through a person than
through a funnel metric, and a request-access form plus a human reply is
how you find out what they actually wanted before the product had to
guess.

## The command

```
python -m auth_service.ops.onboard \
  --email ada@acme.com \
  --display-name "Ada Lovelace"
```

Options: `--locale en|de|uk` (the welcome mail and the workspace;
default `en`), `--workspace-name` to override the default (the email
local part), and `--dry-run` to see exactly what would happen without
creating or sending anything. Run the dry run first if you are unsure
about the address.

What it does, in one transaction: creates the Keycloak user with a
generated password and **no** required actions, creates their personal
workspace, makes them its owner, and marks the account verified —
because you vouched for the address. Then it sends one mail with the
temporary password and a link to change it.

It prints the account id and workspace id. **It does not print the
password**, and the password is not recoverable. That is deliberate: the
only copy in existence is in their mailbox, so it cannot end up in a chat
window or a terminal scrollback. If the mail does not arrive, run the
command again for a fresh one — do not go looking for the old one.

## Then

Reply personally. Include the web link, and the macOS and iOS
instructions if they mentioned a Mac or an iPhone in the form. Tell them
the first thing to do is change the password using the link in the mail.

## Record the request

One row per request, in the shared sheet. Not a system — a sheet:

| source | role | company size | date requested | date onboarded | first note date | notes in week 1 | native app installed | what they said |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

The last column is the one that pays for the other eight. One sentence in
their own words, not a summary. This is the input to the weekly memo and
to the pricing interviews later.

## Rules

Four, and they are not style preferences — each is a way to create an
account that works until the first save and then fails on a missing row:

1. **Never set a password by hand.** The command generates one.
2. **Never use the Keycloak console to onboard.** A user created there
   has no `users` row, no workspace and no membership; they sign in
   successfully and then get a foreign-key error on their first note.
3. **Never write SQL.** Same reason, from the other end: rows without a
   Keycloak user cannot sign in at all.
4. **If the command fails, that is a bug — open an issue.** Do not work
   around it. The command compensates on failure (a Keycloak user created
   before a database error is deleted), so a failure leaves nothing
   half-built and is safe to retry once; a *second* failure is a defect
   in BE-0, not something to route around by hand.

## When it refuses

| It says | What happened | What to do |
| --- | --- | --- |
| `already has an account — nothing to do` | The address is registered | Tell them to sign in, or use "Forgot password?" |
| `MDX_SIGNUP_ENABLED is not set on this deployment` | Onboarding is switched off here | Are you on the right host? Otherwise ask an engineer to set it |
| `signup is not wired: … no mail provider … or no Redis` | The relay or Redis is missing | An account nobody can be told about is not an onboarding. Escalate |
| `MDX_IDP_MODE=native: …` | This deployment no longer uses passwords | Onboard through `/auth/email/start` instead |
| `account created … but the welcome mail FAILED` | The account exists; only the mail did not go | **Do not resend the password.** Tell them to use "Forgot password?" on the sign-in page |

## The other end: people who never finish

Someone who signs up on the web and never confirms keeps their address
reserved, so a later attempt with the same address gets a "you already
have an account" mail they will not understand. That is what
`python -m auth_service.ops.cleanup_invited` is for — see
`docs/runbooks/auth.md § Signup`. It is safe to run on a schedule; it
only touches accounts that never confirmed.

## Request-access form

Hosted (Tally or Typeform — building one is NOT NOW), linked from the
landing page and from `/login` as "Request access". Fields: email, name,
company, role, meetings per week, where you heard about us. Submissions
land in the shared inbox and the Slack channel.
