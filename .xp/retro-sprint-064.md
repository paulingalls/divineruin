# Sprint 64 retrospective

The sprint connects persisted spatial combat, speech and hearing restrictions,
Hollow Resonance and the first playable Named encounter, the Choir. Shared
content contracts are checked in both Python and TypeScript. M33 and M7.3
remain partial; the remaining Named creatures and general spell damage engine
are outside this release.

Working-state ownership was the recurring correctness boundary. Review caught
queued actions invalidated by an earlier successful action, concentrated effects
escaping transaction rollback, and encounter destruction requiring a durable
receipt across reward retries. The engine now distinguishes a refused declaration
from a queued action that became stale, and a committed kill from an uncommitted
reward. Those distinctions are pinned by real persistence and retry checks.

The human expanded close triage to the historical review backlog, with Luna
readers and a high now-or-never bar. The 913 findings received 248 stale, 80 superseded and 583 nit dispositions;
two reproduced issues, credential disclosure and Inner Fire rollback corruption,
warranted immediate fixes. Old verification receipts,
superseded claims and bounded nits receive explicit dispositions rather than
becoming an ordinary follow-up queue. Audit evidence must distinguish current
code inspection from a historical review's assertions.

Focused story checks and static gates keep feedback affordable. Broad regression
is reserved for the final shipping tree. A fixed-roll combat escape demonstrates
a legal bounded outcome, not encounter balance; deterministic local speech
fixtures demonstrate transport and command ownership, not paid-provider speech
recognition quality. Native execution remains a separate acceptance boundary.

All XP roles stay on Codex / GPT-6.1 Sol until the human changes that preference.
Luna was explicitly authorized for historical triage. Background CLI jobs require
active monitoring; the lead continues through handoffs rather than ending a turn
while an executor is still running.

Native acceptance exposed a shared iOS audio-session interaction: the first
combat sound was followed by continuing microphone frames containing silence.
SFX playback now preserves the shared session. With normal microphone settings,
the later run reached eight checkpoints through the legal silenced command. The
human stopped the repetitive speaker output and explicitly deferred completion
and the matched native SFX fault proof. The unfinished native harness is not a
release acceptance pass; its remaining work is recorded in REMAINING.md. Automatic
checks stay silent. Repeated full native rebuilds for small hypotheses cost too
much; the remaining investigation starts at the two-command failure boundary.

The release incorporates origin/main's Sprint 107 before final review. The merge
preserves Iron Resolve's live HUD update alongside transactional Inner Fire
rollback. Focused integration checks caught the attack/save-only bonus leaking
into skill checks through live conditions, and a nonparticipant save consulting
unrelated combat placement. Those boundaries now have passing behavior checks;
merged prompt fixtures preserve both hearing-only inputs and the new gift cue.
