-- M8 story-004 (AC3): the bonus variant a training-track spell was learned with.
-- A spell-training activity records a midpoint decision (e.g. power/control); on
-- promotion the chosen variant is carried onto the known spell so casting can later
-- reflect it. Nullable — discovery-track spells (and pre-existing rows) have none.
-- Written by apps/agent/character_spells.py:record_learned.

ALTER TABLE character_spells
  ADD COLUMN IF NOT EXISTS bonus_variant TEXT;
