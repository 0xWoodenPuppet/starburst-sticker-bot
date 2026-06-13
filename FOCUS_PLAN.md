# Focus Session Handler — Implementation Plan (V1 — ARCHIVED)

> [!NOTE]
> **Status: ARCHIVED.** This was the original "full replacement" plan. We pivoted to a simpler approach (see new implementation plan). Keeping this for future reference when building the full channel feature.

## Resolved Decisions (from comments)

| Question | Decision |
|---|---|
| **Who can host?** | Open to anyone who sends a Forest link |
| **Channel target** | New channel `-1003915074078` ("forest study & work channel") |
| **Bot username** | `@StarburstStickerBot` |
| **AI coach** | Keep it. Single reply only. Compare planned task vs actual task vs self-score. Genuine advice, not cringe/generic. |
| **Sticker on session post** | Yes, keep it |
| **Minutes selection** | Inline buttons 1-10 (like room.py) |
| **Live countdown** | Remove |
| **room_handler** | Don't remove — it doesn't clash, keep it for Notebook of Deku |

A new [handlers/focus.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/focus.py) that replaces the overlapping `session.py` + `room.py` + `coach.py` DM flows with a single, clean handler backed by MongoDB.

## User Review Required

> [!IMPORTANT]
> **Clash Resolution:** This new handler replaces the session lifecycle from three existing files. The following handlers will be **removed from `main.py` registration** (not deleted — just unregistered so you can reference them):
> - `session_handler` from [session.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/session.py) — currently catches Forest links in DM
> - `room_handler` from [room.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/room.py) — currently handles `/room` command + countdown + scoring
> - `handle_dm_reply` from [coach.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/coach.py) — currently catches all DM text for AI coaching
>
> The sticker auto-reply in groups ([messages.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/messages.py)) stays untouched — it only fires on group/channel posts.

> [!WARNING]
> **Bot username required.** Deep links use `https://t.me/BOT_USERNAME?start=task_XXX`. The bot username needs to be configured in [config.py](file:///Users/bilal/repos/starburst-sticker-bot/config.py) (or fetched once at startup via `bot.get_me()`).

## Open Questions

> [!IMPORTANT]
> 1. **Who can host?** Currently `room.py` restricts hosting to `BOT_ADMIN_IDS`, while `session.py` allows anyone in `SESSION_USERS`. Should the new handler keep it admin-only, or open it up?
> 2. **Channel target:** Currently `room.py` posts to a hardcoded `CHANNEL_ID`. Should the new handler use the same channel, or should it be configurable per host (like `SESSION_USERS` maps host → chat)?
> 3. **Keep the AI coach?** The current `coach.py` DMs users after sessions with Gemini follow-up. Should the new "What did you actually do?" step (Step 6) just be the simple button flow, or also include the AI coach conversation?
> 4. **Sticker on session post?** Currently `room.py` sends a tree sticker before the session post. Keep this behavior?

---

## Session Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1: HOST SETUP (Bot DM)                                  │
│                                                                 │
│  Host sends Forest link → Bot parses tree/duration/code         │
│  Bot asks "In how many minutes?" → Host replies with number     │
│  Bot posts session in @channel                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 2: COUNTDOWN (Channel post with 3 buttons)              │
│                                                                 │
│  🌱 Join Session  │  📋 Copy Code  │  ✏️ Write Task            │
│                                                                 │
│  "Join" callback   → records participant + shows link popup     │
│  "Copy Code" callback → records participant + shows code popup  │
│  "Write Task" deep link → /start task_ID → bot DMs for task     │
│                                                                 │
│  Live countdown updates every minute                            │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 3: ACTIVE (Session running)                              │
│                                                                 │
│  Buttons replaced with "⏱ X min left" (no more joining)        │
│  Timer ticks every minute                                       │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 4: REVIEW (Session ended)                                │
│                                                                 │
│  Bot DMs ALL participants:                                      │
│  "Session over! How did it go? /history to see past sessions"   │
│  [✅ Completed] [🦦 Distracted] [⏳ Needs more time]            │
│                                                                 │
│  User taps button → saved to DB                                 │
│  Bot asks: "Anything you want to note?" (optional free text)    │
│  After 10 min timeout → scoring closes                          │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 5: ENDED                                                 │
│                                                                 │
│  Session document finalized in MongoDB                          │
│  /history available for all participants                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## MongoDB Document Schema

### `sessions` collection

```python
{
    "_id": ObjectId,
    "host_id": 1463187459,
    "host_username": "TheWoodenPuppet",
    "tree": "Oak Tree",
    "sticker_id": "CAACAgUAA...",
    "duration": 30,
    "token": "ABC1234",
    "join_link": "https://forestapp.cc/join-room?token=ABC1234",
    "channel_id": -1002511165129,
    "session_msg_id": 456,
    "phase": "ended",  # countdown | active | review | ended
    "start_time": datetime,
    "created_at": datetime,
    "ended_at": datetime,

    # Participants: keyed by str(user_id)
    "participants": {
        "5534874386": {
            "username": "Ari",
            "joined_via": "join_button",  # join_button | copy_code | write_task
            "task": "Study calculus chapter 5",
            "score": "✅",
            "note": "Finished all practice problems",
        },
        "1382116841": {
            "username": "Mochi",
            "joined_via": "write_task",
            "task": "Read biology notes",
            "score": "🦦",
            "note": null,
        }
    }
}
```

---

## Proposed Changes

### New Handler

#### [NEW] [handlers/focus.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/focus.py)

The main new file. Contains:

**Entry points:**
- `ConversationHandler` for Forest link in DM → asks minutes → posts to channel
- `/start` handler with deep link payload parsing (`start=task_SESSION_ID`)
- `CallbackQueryHandler` for `focus_join`, `focus_code`, `focus_score_*` buttons

**Core functions:**
- `_parse_forest_link(text)` — reuse logic from `room.py`
- `_find_tree(text)` — reuse tree sticker lookup from `room.py`
- `receive_link(update, context)` — entry: Forest link in DM
- `receive_minutes(update, context)` — posts session to channel with 3 buttons
- `focus_callback_handler(update, context)` — routes all `focus_*` callbacks
- `_cb_join(query, context)` — records participant, shows link popup
- `_cb_code(query, context)` — records participant, shows code popup
- `handle_deep_link_task(update, context)` — handles `/start task_XXX` → asks for task
- `receive_task_reply(update, context)` — saves task text to DB
- `_countdown_tick(context)` — minute-by-minute countdown job
- `_session_tick(context)` — minute-by-minute active session timer
- `_session_ended(context)` — DMs all participants with scoring buttons
- `_cb_score(query, context)` — records score, optionally asks for note
- `_deactivate_scoring(context)` — 10-min timeout to close scoring

**Inline keyboard layouts:**
```
Countdown phase:
┌──────────────────────────────────────────────────┐
│  ⏱ Starts in X min                              │
├────────────────┬───────────────┬─────────────────┤
│  🌱 Join       │  📋 Code      │  ✏️ Write Task  │
└────────────────┴───────────────┴─────────────────┘

Active phase:
┌──────────────────────────────────────────────────┐
│  ⏱ X min left                                   │
└──────────────────────────────────────────────────┘

Review DM (sent to each participant):
┌──────────────────────────────────────────────────┐
│  ✅ Completed                                    │
├──────────────────────────────────────────────────┤
│  🦦 Distracted                                   │
├──────────────────────────────────────────────────┤
│  ⏳ Needs more time                              │
└──────────────────────────────────────────────────┘
```

---

#### [NEW] [handlers/history.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/history.py)

Handles the `/history` command.

- `history_command(update, context)` — queries MongoDB for user's past sessions
- Default: last 7 days
- `/history 30` → last 30 days
- `/history all` → all time
- Formats a readable summary: date, tree, duration, task, score, note

---

### Modifications

#### [MODIFY] [main.py](file:///Users/bilal/repos/starburst-sticker-bot/main.py)

- **Remove:** `session_handler`, `room_handler`, `room_callback_handler`, `handle_dm_reply` registrations
- **Remove:** `task_command`, `track_forwarded_post`, `monitor_group_messages` registrations (all from room.py)
- **Add:** `focus_handler` (ConversationHandler for DM link flow)
- **Add:** `focus_callback_handler` (CallbackQueryHandler for `focus_*` patterns)
- **Add:** `/start` handler modification to catch deep link payloads
- **Add:** `/history` command handler
- **Add:** DM text handler for task replies (within ConversationHandler, so no clash)

#### [MODIFY] [config.py](file:///Users/bilal/repos/starburst-sticker-bot/config.py)

- Add `BOT_USERNAME` (or fetch dynamically at startup)
- Add `FOCUS_CHANNEL_ID` (the channel where session posts go)

---

### Files Left Untouched

| File | Why |
|---|---|
| [messages.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/messages.py) | Group sticker auto-reply — independent, no clash |
| [mentions.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/mentions.py) | Forest mention system — filters by specific group chat only |
| [scoring.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/scoring.py) | 7-day challenge system — completely separate feature |
| [daily.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/daily.py) | Scheduled broadcasts — independent |
| [ask.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/ask.py) | `/ask` command — independent |
| [db.py](file:///Users/bilal/repos/starburst-sticker-bot/db.py) | Already created and tested ✅ |

### Files Retired (unregistered, not deleted)

| File | Replaced By |
|---|---|
| [session.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/session.py) | `focus.py` — DM link entry + countdown |
| [room.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/room.py) | `focus.py` — full session lifecycle |
| [coach.py](file:///Users/bilal/repos/starburst-sticker-bot/handlers/coach.py) | `focus.py` — review step replaces coach DM |

---

## Deep Link Flow Detail

```
Button URL:  https://t.me/BOT_USERNAME?start=task_SESSION_MONGO_ID

When user clicks:
  1. Telegram opens bot DM
  2. Telegram sends: /start task_6a2ac597366527b448baae71
  3. Bot's /start handler parses payload
  4. Looks up session by _id in MongoDB
  5. Checks session is in countdown/active phase
  6. Bot replies: "What's your task for this session?"
  7. User types task → saved to DB
  8. User added as participant on channel post (edited)
```

For users who haven't started the bot before: Telegram shows a "START" button — standard behavior, no special handling needed. The deep link payload is preserved.

---

## Verification Plan

### Manual Verification
1. Host sends Forest link in bot DM → verify countdown post appears in channel with 3 buttons
2. Click "Join" → verify popup with link + participant recorded in MongoDB
3. Click "Copy Code" → verify popup with code + participant recorded
4. Click "Write Task" → verify deep link opens bot DM → ask task → save to DB
5. Session countdown → active → ends → verify DM sent to all participants
6. Tap score button in DM → verify saved to DB
7. Run `/history` → verify past sessions displayed correctly
8. Restart bot → verify no data lost (MongoDB persistence)
9. Check MongoDB Atlas dashboard to visually confirm documents

|# suggestions
The AI coach question matters more than it seems. The "What did you actually do?" reflection step is where retention comes from. A simple button (✅/🦦/⏳) is low friction but also low value. Dropping Gemini entirely might be a mistake — even a single follow-up question would improve it.

The countdown edit loop is a silent failure risk. Editing a channel message every minute via bot.edit_message_text will hit Telegram's rate limits if multiple sessions run concurrently, and silently fail in ways that confuse users. You'll want explicit error handling around every edit call.

The countdown edit loop is a silent failure risk. Editing a channel message every minute via bot.edit_message_text will hit Telegram's rate limits if multiple sessions run concurrently, and silently fail in ways that confuse users. You'll want explicit error handling around every edit call.

The main thing holding it back from a higher score is that the most differentiating part — the post-session reflection and history — is the least developed part of the spec.

These two features are actually the same feature looked at from different ends — reflection is data input, history is data output. The way to make both better is to make the data richer and more personal.

The task field is currently set at join time and never revisited. At review time, ask: "You planned: 'Study calculus ch5' — did you actually do that?" with buttons [Yes, exactly that]  [Partially]  [Ended up doing something else]. If "something else", let them type what. This creates a declared-vs-actual gap metric that's genuinely interesting over time.
Keep a lightweight AI coach but make it opt-in. Rather than Gemini DMing everyone after every session, add a [💬 Reflect with AI] button in the review DM. Tapping it opens the coaching conversation. Users who want it get it; others aren't bothered.

Personal patterns. With enough sessions you can show: "Your average focus depth on 45-min sessions is higher than 30-min sessions" or "You're 2x more likely to be distracted on Fridays." This is the kind of insight that makes users feel the bot actually knows them.
Session comparison. "Last time you studied calculus (Jun 5), you scored ✅ in 45 min. This time you scored 🦦 in 30 min." Surfacing the previous session for the same task type at review time creates a natural self-comparison loop without any extra work from the user.

The unifying principle: right now reflection is a closing ritual, and history is a record. The upgrade is making reflection feel like the start of a conversation and history feel like a mirror. The data schema you already have supports all of this — it's mostly a product design and prompting problem, not a technical one.

Image Template for /history — Is It Worth It?
Short answer: yes, it's a good idea, and no, it won't be a load problem for your scale.
Here's the full breakdown:
The load concern is real but manageable. Generating a Pillow image is CPU work, not network work. For a small community bot, /history will be called maybe a few times a day — that's nothing. Even at 100 users calling it simultaneously (unlikely), Pillow image generation takes ~50-200ms per image. It's fine.
The bigger concern is the right one: file size. Telegram compresses photos aggressively. If you send as sendPhoto, Telegram re-encodes it as JPEG and users can't see fine text clearly. The fix is to send it as a document (sendDocument) instead — it arrives uncompressed, renders as a preview, and text stays crisp. This is what Spotify Wrapped-style bots do.
You can send a Pillow image directly without saving to disk by writing it to a BytesIO buffer and passing that to send_photo — no temp files needed. Same works for send_document. Hedge3
What the image card buys you that text doesn't:

It's shareable. A user can screenshot or forward it as a flex. Text history isn't.
It has visual hierarchy — you can make the streak number huge and the details small, which text formatting in Telegram can't do well.
It feels like a product, not a debug log.

Keep the card narrow (like 600×400px) so it renders well as a photo preview in chat. Use a dark background — it reads better in Telegram's dark mode which most users are on.
One practical tip: generate the image async so the bot doesn't block while Pillow draws. In python-telegram-bot, wrap the generation in asyncio.to_thread() since Pillow is synchronous CPU work.

If duration can't be parsed → send the sticker as usual (no button, no tracking). Clean fallback.

On the language question: your existing regex in 

session.py L92
 already handles 10+ languages (min, 분, 分, دقيق, perc, dakik, мин, menit, मिनट). So most cases are already covered. But yes — if you want to be thorough, getting a sample Forest invite in each language the bot's users actually use would help catch edge cases.