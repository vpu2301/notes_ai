# Load test — shared page (Sprint 23)

Script: `tests/load/shared_page.js` (k6). Profile: 50 requests/second for
10 minutes against `GET /v1/shared/{token}`, logo every tenth request.
Pass bar: p95 ≤ 300 ms, error rate < 0.1 %.

Run against **staging** only (each request is a view on the link):

    k6 run -e BASE=https://api.staging.example -e TOKEN=<recipient token> \
      --summary-export docs/testing/load/shared-page-$(date +%F).json tests/load/shared_page.js

Commit the summary JSON here. No run has been recorded yet: the script
was written on 2026-09-17 and needs a staging deployment of migration
0041 to run against.
