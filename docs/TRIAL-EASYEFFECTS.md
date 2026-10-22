# EasyEffects activity and conditional preparation

Preparation is read-only and is not authorization for a real trial. An idle graph
can produce a plan, but cannot authorize the first intervention.

## Why a missing link is not always a fault

EasyEffects v8.2.9 keeps its virtual sink and final level meter while its inactivity
handler can unlink the output processing chain, including the final device links.
The default timeout is enabled at ten seconds. Active application links into its
sink trigger rebuilding; a media player's MPRIS Playing status is not that signal.
See the upstream [implementation](https://github.com/wwmm/easyeffects/blob/v8.2.9/src/stream_output_effects.cpp)
and [defaults](https://github.com/wwmm/easyeffects/blob/v8.2.9/src/contents/kcfg/easyeffects_db.kcfg).

The private real-EasyEffects regression reproduces active -> idle -> late active
without manually creating processing/output links. The same sink/meter identities
survive. This demonstrates a legitimate state; historical snapshots alone cannot
prove which callback ran at a particular instant or that future playback will work.

## Two distinct outcomes

- `IDLE_UNPROVEN`: no effective playback activity observed. The output pair may be
  completely absent or complete, never partial, crossed, duplicated or sent elsewhere.
  Preparation may save this state; processing and destination readiness are unproven.
- `ACTIVE_VERIFIED`: an uncorked Pulse stream, running native playback node or active
  application link requires a complete reviewed path. Every playback destination
  must be the identified effects sink, with established links into it. Both channel
  paths through owned EE processing nodes must reach the identified output meter,
  then FL -> FL and FR -> FR of the split virtual, with acceptable link states.

The sink, output meter and client must have coherent ownership. The client process
identity and serial are checked; changing the owner, adding ambiguity or changing
pinned identities is not a legitimate idle transition. The private null stand-in
is accepted only by fixture configuration; the production entry point requires
actual BlueZ endpoints and the real EasyEffects application identity.

Pulse/graph captures are checked for relevant topology/activity consistency.
Up to three bounded read attempts are allowed for a changing snapshot; continued
change fails closed. No links or media commands are emitted by preparation. During evaluation, a newly
active stream may need asynchronous rebuilding: incomplete paths get at most a
1.25 s read-only settling interval, bounded also by the global deadline. Incorrect
destinations, crossed routes, duplicate routes and foreign ownership fail immediately.

## From preparation to intervention

Schema 3 records the activity classification and code hashes. Older schemas require
new preparation. An idle plan can arm the persistent supervisor after separate
explicit authorization. The user starts the reference A normally. Immediately
before freeze, a fresh capture must be ACTIVE_VERIFIED with unchanged identities
and matching captured routes/stream identities. Otherwise the trial ends
ABORTED_UNCHANGED, without freeze, mute, removal or rollback writes.

The deadline still starts at ARMED. Starting playback does not extend the arm
window or the 600 s overall limit, 360 s return deadline and 30 s warning. A plan
prepared while idle is not proof that B can be evaluated acoustically.

## Return and dynamic resources

The final pre-intervention snapshot supplies levels/mute, destinations and the
original fan-out. Before return, surviving and newly created playback streams are
captured by serial; no recreated application is moved by name. Valid current EE
input links are recorded. If playback has become idle and those links are absent,
return does not resurrect the historical pair. If the candidate died while
playback remained active, recovery is limited to previously verified EE ports and
the reviewed intended route, never an arbitrary new destination.

The same owned-resource ledger, current identity guards, foreign-link preservation
and verification before/after watchdog resumption remain in force. Unknown capture
or application state remains an explicit limitation. A persistent recovery failure
is FAILED, never claimed success. Media playback is never commanded.

## Regression coverage

Unit tests cover active and idle, late/removed streams, torn snapshots, missing
processing, wrong/crossed/duplicate/incomplete output routes even while idle,
foreign/ambiguous ownership, owner replacement and no writes on a refused start.
The full private supervisor runs its eleven existing scenarios both with a null
stand-in and real EE. Additional real-EE scenarios arm idle, create playback before
the final snapshot, create another application during B, and stop playback during B
so EE unlinks before return. The latter must return without recreating EE inputs.
CI installs real EE and exercises its lifecycle in isolated runtimes.

Return verification records expiring edges with node serials and a verified role:
EE-owned internal output processing, or identified application playback into EE.
Their disappearance is not treated as loss of unrelated resources. All other
foreign links remain mandatory. Current effective routing and ownership are checked
again before and after watchdog resumption. If playback ends after the return
snapshot, the EE input pair becomes optional; existing wrong links still fail.
