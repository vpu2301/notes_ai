# Sprint F1 T3 — speech coverage, measured before shipping

**Report:** `asr-coverage-2026-10.json, asr-coverage-2026-10-no-pad.json` (`scripts/eval/coverage_eval.py`, git `188dd64`). **Engine:** in-process `large-v3`, int8, cpu. **Files:** vc-atgpi (122 s), vc-ampme (148 s), vc-afjiv (151 s), vc-eqttu (161 s), vc-djngn (173 s), vc-gpjne (185 s), vc-azisu (194 s), incident (166 s).

## Configurations

| | today | pad | pad_floor | pad_floor_second | floor_second |
|---|---|---|---|---|---|
| Coverage share (VAD speech transcribed) | 96.5 % | 95.6 % | 95.6 % | 100.0 % | 100.0 % |
| Reference speech covered (RTTM, speakers files) | 95.4 % | 95.8 % | 95.8 % | 99.2 % | 97.2 % |
| Word change vs today (WER bound) | 0.0 % | 9.6 % | 9.6 % | 9.0 % | 3.1 % |
| Word change vs the configuration before | 0.0 % | 9.6 % | 0.0 % | 5.0 % | 6.6 % |
| vs today: inserted / deleted / substituted | — | 1.6 % / 3.3 % / 5.2 % | 1.6 % / 3.3 % / 5.2 % | 3.8 % / 1.8 % / 3.9 % | 3.1 % / 0.0 % / 0.0 % |
| Second-pass chunks per audio hour | 0.0 | 0.0 | 0.0 | 5.5 | 5.5 |
| Inference seconds per audio hour | 14350 | 9794 | 9794 | 10154 | 6707 |
| Inference vs today | 1.00× | 0.68× | 0.68× | 0.71× | 1.02× |
| Verdict | eligible | deleted + substituted 8.5 % > 0.5 pt | deleted + substituted 8.5 % > 0.5 pt | deleted + substituted 5.7 % > 0.5 pt | **shipped** |

**Shipped: `floor_second`.** Rule: highest coverage whose deleted + substituted words against today are ≤ 0.5 pt (the WER bound; inserted words are speech a gap had swallowed) and inference ≤ 1.2× today. Inference seconds are wall time on a shared machine: runs that overlapped another eval read slower than they are.

**WER: the speakers corpus carries RTTM only; word change vs today bounds the WER delta.** **DER: none of the changes touches the diarizer's input or labels; not re-measured.**

## Per file

| File | today | pad | pad_floor | pad_floor_second | floor_second |
|---|---|---|---|---|---|
| vc-atgpi | 100.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % |
| vc-ampme | 100.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % |
| vc-afjiv | 100.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % |
| vc-eqttu | 100.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % |
| vc-djngn | 85.9 % (148–172 s unknown) | 85.9 % (148–172 s unknown) | 85.9 % (148–172 s unknown) | 100.0 % | 100.0 % |
| vc-gpjne | 100.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % |
| vc-azisu | 100.0 % | 84.4 % (118–148 s unknown) | 84.4 % (118–148 s unknown) | 100.0 % | 100.0 % |
| incident | 85.6 % (99–119 s unknown) | 100.0 % | 100.0 % | 100.0 % | 100.0 % |

## The Pardo recording (r02)

- **Stored transcript, before the fix:** coverage 63.6 %, first speech 11.7 s, first segment 40.9 s; gaps 12–42 s (unknown), 99–119 s (unknown); r02 {'coverage_share>=0.98': 'FAIL', 'must_contain_before_ms[0]': 'FAIL', 'must_contain_before_ms[1]': 'FAIL'}. The stored artifact predates diagnostics (has diagnostics: False), so code cannot name the cause; the I3 evidence note does: the old whole-segment prompt-echo drop (`prompt_echo`).
- **today:** coverage 85.6 %, first segment 11.7 s, second pass 0 chunk(s) / 0 words; r02 {'coverage_share>=0.98': 'FAIL', 'must_contain_before_ms[0]': 'PASS', 'must_contain_before_ms[1]': 'PASS'}.
- **pad:** coverage 100.0 %, first segment 11.4 s, second pass 0 chunk(s) / 0 words; r02 {'coverage_share>=0.98': 'PASS', 'must_contain_before_ms[0]': 'PASS', 'must_contain_before_ms[1]': 'PASS'}.
- **pad_floor:** coverage 100.0 %, first segment 11.4 s, second pass 0 chunk(s) / 0 words; r02 {'coverage_share>=0.98': 'PASS', 'must_contain_before_ms[0]': 'PASS', 'must_contain_before_ms[1]': 'PASS'}.
- **pad_floor_second:** coverage 100.0 %, first segment 11.4 s, second pass 0 chunk(s) / 0 words; r02 {'coverage_share>=0.98': 'PASS', 'must_contain_before_ms[0]': 'PASS', 'must_contain_before_ms[1]': 'PASS'}.
- **floor_second:** coverage 100.0 %, first segment 11.7 s, second pass 1 chunk(s) / 34 words; r02 {'coverage_share>=0.98': 'PASS', 'must_contain_before_ms[0]': 'PASS', 'must_contain_before_ms[1]': 'PASS'}.

## Outcome

- **Shipped: floor on, second pass on, pad off** (`MD_ASR_VAD_PAD_MS=0`). The second pass
  changed words only inside the two gaps it closed (djngn +86, Pardo +35 words); the six files
  without a gap are word for word today's transcript. The 300 ms pad reshuffled chunk
  boundaries on every file (3.3 % deleted, 5.2 % substituted) and opened a gap on vc-azisu
  that only the second pass then closed — its effect on WER cannot be shown to be within
  0.5 pt, so it stays in the code, off.
- **The floor never fired** on these files (no file has < 20 % speech with a loud rest); it is
  bounded to that condition and measured on the synthetic quiet-call fixture in the unit suite.
- **Pardo (acceptance 1):** introduction present (Mitchell, Springbrook before 00:60) and
  coverage 100 %. The pre-fix artifact's gaps (12–42 s, 99–119 s) carry no diagnostics; the
  first is the old whole-segment prompt-echo drop (I3 evidence note), the second the
  mixed-language chunk the second pass now recovers.
- **Gold-set coverage share ≥ 0.98 (acceptance 2):** 100 % of VAD speech; 97.2 % of the
  RTTM reference speech is within reach of a word (the reference also marks laughter and
  backchannels VAD does not call speech).
- **Not measured:** WER (RTTM-only corpus; the word-change split above is the bound), DER (not
  touched), the AMI half of the speakers set and the notes gold set (in-process CPU decoding at
  about half real time — a subset was measured, named at the top).
