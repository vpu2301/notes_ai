-- 0088 — Sprint P1 (the writer): the note a generation wrote, as Markdown (its first
-- line is the title), and the items parsed from it in their exact order. NULL / 0 for
-- every run of the removed path. No backfill. RLS as on the tables already.

ALTER TABLE note_generations ADD COLUMN text TEXT;

ALTER TABLE note_generated_items
    ADD COLUMN position     INTEGER NOT NULL DEFAULT 0,
    -- A table row's cells (`{"header": [...], "cells": [...]}`); NULL for a bullet or a paragraph.
    ADD COLUMN table_row    JSONB
        CHECK (table_row IS NULL OR (jsonb_typeof(table_row) = 'object' AND pg_column_size(table_row) <= 4096)),
    -- The time named no turn exactly: the nearest one is cited.
    ADD COLUMN cite_nearest BOOLEAN NOT NULL DEFAULT false;

-- The writer's kinds join the vocabulary (older rows keep theirs).
ALTER TABLE note_generated_items DROP CONSTRAINT IF EXISTS note_generated_items_kind_vocab_check;
ALTER TABLE note_generated_items ADD CONSTRAINT note_generated_items_kind_vocab_check
    CHECK (kind IN (
        'action', 'agenda_item', 'blocker', 'budget_timeline', 'candidate_fact', 'challenge',
        'client_request', 'commitment_ours', 'commitment_theirs', 'competitor_mention',
        'completion', 'concern', 'decision', 'feedback_given', 'feedback_received',
        'growth_topic', 'judgement', 'key_point', 'need', 'next_meeting', 'objection',
        'open_question', 'progress', 'question', 'risk', 'stakeholder', 'status_statement',
        'strength', 'user_point', 'win',
        'summary_sentence', 'framing', 'topic_bullet', 'date',
        'figure', 'introduction', 'next_step', 'claim',
        'bullet', 'paragraph', 'vote', 'table_row'
    ));

-- The writer's one step joins the vocabulary (older rows keep theirs).
ALTER TABLE note_generations DROP CONSTRAINT IF EXISTS note_generations_step_check;
ALTER TABLE note_generations ADD CONSTRAINT note_generations_step_check
    CHECK (step IS NULL OR step IN ('extract', 'write_items', 'reduce', 'write_doc', 'write'));

-- The writer replaces a generation's rows in one transaction (the delete policy existed
-- since 0052; the grant did not).
GRANT DELETE ON note_generated_items TO app_role;
