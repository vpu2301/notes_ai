# Ambient capture — business use cases

Where an "ambient scribe" (a microphone that listens to a conversation
and produces a speaker-attributed, structured note) earns its keep in a
business setting. Grouped by how directly the platform supports them
today; every scenario maps onto one of the three capture paths in
`docs/architecture/ambient-capture.md` and one of the shipped note
templates (`infra/seeds/templates/`).

## Strong fits today

**Internal meetings (room device or laptop in the room).**
Project reviews, steering meetings, retros, standups. The room device
captures ambiently; the `meeting_notes` template structures the output
(attendees, agenda, discussion, decisions, action items). The
attributed dialogue answers the perennial "who committed to that?".

**Sales calls & customer visits (mobile/live or upload).**
In-person demos, showroom conversations, field sales visits. A rep
records on a phone, uploads with `diarize=true`, and gets a
`sales_call` note (deal stage, objections, next steps) with the
customer's words verbatim — CRM-ready without evening write-ups.

**Recruiting interviews (room device or live).**
Panel and 1:1 interviews captured ambiently free the interviewers to
engage; the `interview_debrief` template (recommendation choice field)
turns the raw dialogue into a calibrated debrief. Attribution matters:
what the candidate said vs. what an interviewer paraphrased.

**Professional-services client sessions (all paths).**
Consulting workshops, financial advisory meetings, agency briefings,
legal intake conversations. The billable-hours world runs on accurate
meeting records; attributed transcripts are also the raw material for
scope documents and engagement letters. (Regulated verticals bring
their own consent/retention duties — see the posture note below.)

**Workshops & brainstorms (room device).**
Design sprints, architecture discussions, planning offsites. Nobody
scribes a whiteboard session well; ambient capture keeps the ideas and
who raised them, and the note's action-items section catches the
follow-ups that usually evaporate.

**Board / committee / governance minutes (room device).**
Formal minutes need accuracy and attribution more than speed. The
hash-chained, versioned note (finalize → amend with full history) fits
the governance requirement that minutes be tamper-evident.

**1-on-1s and coaching conversations (live).**
The `one_on_one` template plus live capture keeps the manager present
instead of note-taking. Sensitive by nature — deployments should pair
this with explicit participant consent.

## Adjacent fits (same pipeline, light product work)

- **Field service & inspections** — technicians narrating site visits,
  insurance claim walk-throughs, property surveys: today's dictation
  mode already covers the solo-voice case; ambient adds the
  customer-present case.
- **Support escalations & QBRs** — record the call (where the call
  platform allows export), upload, attach the note to the account.
- **Training & sales coaching** — capture role-plays and real calls,
  review attributed transcripts against a rubric.
- **Multilingual meetings** — uk/en (de plumbing present) transcription
  makes cross-language teams' notes searchable in one place.

## Deliberate non-goals

- **Identifying who a voice belongs to.** Labels are neutral
  `SPEAKER_N`; humans assign names. Voice-print identification is a
  privacy cliff we stay away from.
- **Covert recording.** The backend attributes every capture to a
  device/user and audits every session; consent workflow and
  jurisdictional recording rules are the deployer's obligation and
  should be handled in the product UI (announcements, consent prompts).

## Posture note for regulated buyers

Legal, financial, and HR conversations carry confidentiality and
retention duties. The platform's per-tenant envelope encryption, RLS
isolation, tamper-evident audit chain, and PII-free notification
policy are the foundation; deployment-specific retention and consent
policy sit above it.
