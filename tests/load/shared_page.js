// k6 — the shared page under load (Sprint 23, B-6).
//
//   k6 run -e BASE=https://api.staging.example -e TOKEN=<a live recipient token> tests/load/shared_page.js
//
// 50 rps sustained for 10 minutes against GET /v1/shared/{token}, with
// the logo fetched every 10th request (cache hit path). Thresholds are
// the sprint's acceptance bar; the run's summary goes to
// docs/testing/load/. Never point this at production: every request
// counts as a view on the token's link.
import http from "k6/http";
import { check } from "k6";

export const options = {
  scenarios: {
    steady: { executor: "constant-arrival-rate", rate: 50, timeUnit: "1s", duration: "10m", preAllocatedVUs: 60, maxVUs: 200 },
  },
  thresholds: {
    http_req_duration: ["p(95)<300"],
    http_req_failed: ["rate<0.001"],
  },
};

const BASE = __ENV.BASE;
const TOKEN = __ENV.TOKEN;

export default function () {
  const page = http.get(`${BASE}/v1/shared/${TOKEN}`, { tags: { name: "shared_page" } });
  check(page, { "page 200": (r) => r.status === 200, "has items": (r) => r.json("items") !== undefined });
  if (__ITER % 10 === 0) {
    const logo = http.get(`${BASE}/v1/shared/${TOKEN}/logo`, { tags: { name: "shared_logo" } });
    check(logo, { "logo 200 or 404": (r) => r.status === 200 || r.status === 404 });
  }
}
