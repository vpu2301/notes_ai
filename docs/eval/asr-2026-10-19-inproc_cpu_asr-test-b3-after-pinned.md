# ASR eval — inproc_cpu_asr — test (2026-10-19)

Model `large-v3`, git `51b4e7b`, corpus manifest `650ec9e63a99`, hint `none`, language `pinned`. Numbers and ids only.

| group | n | TR-01 WER | TR-02 halluc chars/min | TR-02 artefacts | TR-03 coverage | TR-03 unexplained gaps | TR-04 entity err | TR-04 num/date err | TR-05 consistency | TR-06 code-switch | TR-06 foreign WER | TR-06 translated | TR-02 loops | B3 re-decode rate | TR-07 marked | TR-08 ts median ms | TR-08 ts p90 ms | TR-09 punctuated | TR-12 rtf p95 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| de | 2 | not measured (n < 3) | | | | | | | | | | | | | | | | | |
| uk | 1 | not measured (n < 3) | | | | | | | | | | | | | | | | | |
| en | 0 | not measured (n < 3) | | | | | | | | | | | | | | | | | |
| code_switch | 2 | not measured (n < 3) | | | | | | | | | | | | | | | | | |
| all (directional) | 3 | 0.039 | — | 0 | 1.000 | 0 | — | — | — | 1.000 | 0.000 | 0 | 0 | 0.000 | — | — | — | 1.000 | 2.194 |

Directional: n < 20 per language. Not measured: n < 3 (never a pass).
WER on speech regions after `asr_scoring.normalise`; hallucination counts
music, jingle, silence and noise regions, not ad reads.
