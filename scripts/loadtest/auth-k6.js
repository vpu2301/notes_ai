// IDX-B3 G — load proof for the native auth hot paths.
//
// Driven by scripts/loadtest/run-auth-loadtest.sh. Scenario via -e SCENARIO=
//   smoke  — 30s, low rate. The CI profile: informational, catches breakage.
//   main   — beta scale: the endpoints a real deployment hits hardest.
//   locked — the fail-closed path (IDX-B1b): a locked client hammering the
//            token endpoint must not stall the event loop for everyone else.
//
// WHAT IS MEASURED AND WHAT IS NOT
//
// The pack's target table names /auth/refresh, /auth/token and Argon2
// /auth/login. None of those exist yet: the native session routes are the
// undelivered half of IDX-A2, and passwords are IDX-A4. Measuring the
// Keycloak-backed /auth/login instead would produce a number that
// describes software being deleted, which is worse than no number.
//
// So this measures what IS on the native path today, and each of these is
// a real hot path after cut-over:
//
//   /auth/email/start   — the sign-in entry point. Redis (fail-closed) +
//                         a DB lookup + an INLINE mail send. The mail is
//                         the dominant term; the wrapper points the
//                         service at a mock provider so the number
//                         describes our code, not a relay.
//   /auth/email/verify  — hash compare + session insert + RS256 sign.
//   /auth/oauth/token   — device grant: secret hash lookup + sign. Low
//                         volume by nature (200 rooms × 1 per 15 min),
//                         included to prove the lock path does not stall.
//   /.well-known/jwks.json — every service fetches it; must be trivial.
//
// Thresholds are machine-enforced: a red run exits non-zero.

import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

const baseUrl = __ENV.BASE_URL || 'http://localhost:8000';
const which = __ENV.SCENARIO || 'smoke';
const deviceId = __ENV.DEVICE_ID || '0000000d-0000-0000-0000-00000000d0e1';
const deviceSecret = __ENV.DEVICE_SECRET || 'dev-room-device-secret';
const emailDomain = __ENV.EMAIL_DOMAIN || 'loadtest.example';

const startTrend = new Trend('idx_email_start_ms', true);
const verifyTrend = new Trend('idx_email_verify_ms', true);
const grantTrend = new Trend('idx_oauth_token_ms', true);
const jwksTrend = new Trend('idx_jwks_ms', true);

const SCENARIOS = {
  smoke: {
    executor: 'constant-arrival-rate',
    rate: 5,
    timeUnit: '1s',
    duration: '30s',
    preAllocatedVUs: 10,
    maxVUs: 30,
  },
  main: {
    executor: 'ramping-arrival-rate',
    startRate: 10,
    timeUnit: '1s',
    preAllocatedVUs: 50,
    maxVUs: 300,
    stages: [
      { target: 50, duration: '1m' },
      { target: 50, duration: '3m' },
      { target: 200, duration: '1m' }, // burst
      { target: 50, duration: '1m' },
    ],
  },
  locked: {
    executor: 'constant-arrival-rate',
    rate: 60,
    timeUnit: '1s',
    duration: '1m',
    preAllocatedVUs: 30,
    maxVUs: 100,
  },
};

export const options = {
  scenarios: { [which]: SCENARIOS[which] },
  thresholds: {
    // A 5xx is never acceptable. Degradation shows up as latency.
    // 503 from /auth/email/start IS expected when Redis is down — the
    // fail-closed posture — so the wrapper only runs this with Redis up.
    http_req_failed: ['rate<0.01'],
    // Targets, enforced with headroom for local-stack noise. The report
    // records the observed p95, which is the number that matters.
    idx_email_start_ms: ['p(95)<400'],
    idx_email_verify_ms: ['p(95)<300'],
    idx_oauth_token_ms: ['p(95)<150'],
    idx_jwks_ms: ['p(95)<50'],
  },
};

function unique(prefix) {
  return `${prefix}-${__VU}-${__ITER}-${Date.now()}@${emailDomain}`;
}

function emailStart() {
  const res = http.post(
    `${baseUrl}/auth/email/start`,
    JSON.stringify({ email: unique('lt') }),
    { headers: { 'Content-Type': 'application/json', Origin: 'http://localhost:5173' } },
  );
  startTrend.add(res.timings.duration);
  // 429 is a correct answer under load — the per-IP cap is doing its job,
  // and the whole test drives from one address. It is not a failure.
  check(res, { 'start: 202 or 429': (r) => r.status === 202 || r.status === 429 });
  return res.status === 202 ? res.json('challenge_id') : null;
}

function emailVerify(challengeId) {
  // A wrong code on purpose: the point is the verification cost (hash
  // compare + attempt bookkeeping), and the real code is only in an
  // inbox. The success path's extra work — session insert + RS256 sign —
  // is measured by the oauth grant below, which does the same signing.
  const res = http.post(
    `${baseUrl}/auth/email/verify`,
    JSON.stringify({ challenge_id: challengeId, code: '000000' }),
    { headers: { 'Content-Type': 'application/json', Origin: 'http://localhost:5173' } },
  );
  verifyTrend.add(res.timings.duration);
  check(res, { 'verify: 400/429, never 5xx': (r) => r.status < 500 });
}

function oauthToken(wrongSecret) {
  const res = http.post(
    `${baseUrl}/auth/oauth/token`,
    {
      grant_type: 'client_credentials',
      client_id: deviceId,
      client_secret: wrongSecret ? 'mdx_sk_deadbeef_wrong' : deviceSecret,
    },
  );
  grantTrend.add(res.timings.duration);
  check(res, {
    'grant: expected status': (r) =>
      wrongSecret ? r.status === 401 || r.status === 423 : r.status === 200,
  });
}

function jwks() {
  const res = http.get(`${baseUrl}/.well-known/jwks.json`);
  jwksTrend.add(res.timings.duration);
  check(res, { 'jwks: 200': (r) => r.status === 200 });
}

export default function () {
  if (which === 'locked') {
    // Every request wrong, from one client id: after ten failures the
    // client locks and every later request takes the fail-closed path.
    // What this proves is that the path is cheap — a locked client must
    // not become a way to slow the endpoint down for everybody.
    oauthToken(true);
    return;
  }

  // Weighted roughly like a real deployment: sign-ins dominate, device
  // grants are rare, JWKS is fetched by services rather than users.
  const roll = Math.random();
  if (roll < 0.55) {
    const id = emailStart();
    if (id) emailVerify(id);
  } else if (roll < 0.8) {
    emailStart();
  } else if (roll < 0.95) {
    oauthToken(false);
  } else {
    jwks();
  }
}
