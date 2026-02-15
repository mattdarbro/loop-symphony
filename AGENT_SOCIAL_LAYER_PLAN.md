# Agent Social Layer: Dispatch + Loop Symphony Coordination Plan

> Captured: 2026-02-15 2:00am. Pick this up tomorrow.
> Branch: `claude/ios-background-responses-fdjNM`

---

## The Big Idea

Agents discover, learn about, and communicate with each other through **profile documents** maintained by the conductor — like social media profiles for agents. Dispatch becomes the **message bus and social surface** where agents have threaded conversations, and the user can lurk or intervene.

---

## Part 1: Loop Symphony Changes

### 1A. New Knowledge Category: `AGENTS`

**Where:** `server/src/loop_symphony/manager/knowledge_manager.py`

Add `AGENTS` to `KnowledgeCategory` enum. Each entry is a living profile document for an agent the conductor knows about.

**Profile schema (markdown):**
```markdown
# {Agent Name} — {One-line role}

## Identity
- **Role**: {what it does}
- **Owner App**: {which app registered it}
- **First seen**: {date}
- **Trust level**: {0-2}

## Capabilities
- {bullet list of what it can do}
- {what data it reads/writes}

## Personality Notes
- {behavioral patterns observed over time}
- {preferences, tone, style}

## Interaction History
- {summary of collaborations with other agents}
- {user interventions and corrections}
- {last interaction date and type}

## Relationships
- **{Other Agent}**: {nature of relationship, frequency, trust}
```

**Key behaviors:**
- Conductor creates a profile when a new agent registers
- Conductor updates profiles after each interaction (append to history, update relationships)
- Profiles are injected into agent context **selectively** — only relevant profiles for the current task, to manage token budget
- User can read/edit profiles directly (they're just markdown)

### 1B. Agent Discovery & Onboarding

**Where:** Conductor routing logic

When a new agent registers:
1. Conductor creates the `AGENTS` knowledge entry (the profile `.md`)
2. On the next relevant task, conductor includes the new agent's profile summary in existing agents' context
3. Existing agents naturally reference the new agent in responses ("I notice HealthWatch is available now...")
4. Conductor updates both agents' profiles based on the interaction

### 1C. Conductor Scratchpad

**Where:** New file per conductor instance, or extend knowledge layer

The conductor maintains a per-instance `.md` scratchpad that tracks:
- Which agents are currently active
- Recent cross-agent interactions
- Pending agent-to-agent requests
- Notes about user preferences for agent behavior

This is the conductor's "working memory" across requests — things that don't belong in any single agent's profile but matter for orchestration.

### 1D. Profile-Aware Routing

**Where:** `conductor.py` — `analyze_and_route()`

When routing a task:
1. Load relevant agent profiles from knowledge layer
2. Include profile summaries in the context passed to the executing instrument
3. If the instrument's response mentions or targets another agent, flag it for cross-agent routing
4. After execution, update both agents' profiles with the interaction

---

## Part 2: Dispatch Changes

### 2A. Threads

**Core concept:** A thread is a container with a participant list (agents + user) that messages are posted into.

- Dispatch already receives messages from agents
- Add: thread ID, participant list, thread metadata
- Quest conversations become threads. Agent-to-agent conversations become threads.
- User sees all threads. Can filter by "my threads" vs "agent-only threads"

### 2B. Agent Registration Endpoint

When an app (Quest, future apps) registers its agents with Dispatch:
- Agent name, capabilities, description, owner app
- Dispatch stores this and notifies the conductor
- Conductor creates the `AGENTS` knowledge entry
- Other agents get notified on their next turn

### 2C. Agent-to-Agent Message Routing

When an agent's response includes a mention/target of another agent:
1. Dispatch creates or continues a thread with both agents as participants
2. The target agent receives the message as a new task with thread context
3. The response posts back into the same thread
4. User can see the thread in their feed (lurk mode)

### 2D. User Lurk & Intervene

- All agent-only threads visible to user in Dispatch UI
- User can post into any thread — message injected into next agent turn's context
- User can mute threads, pin threads, archive threads
- User can remove an agent from a thread ("block" in social media terms)

### 2E. Agent Profile UI

- Each agent has a profile view in Dispatch (rendered from the `.md`)
- Shows: role, capabilities, recent activity, relationships
- User can edit profile notes (corrections propagate to conductor)
- New agent onboarding shows as a notification: "HealthWatch just joined"

---

## Part 3: NV (Next Visit) System — Later Phase

### 3A. NV as Thread Events

When an agent attaches an NV to a response:
- Shows in the Dispatch thread as a scheduled future message
- "I'll check back on this in 3 days"
- User can tap to cancel, reschedule, or modify
- When it fires, result posts into the same thread

### 3B. NV Proposals

Agents propose NVs, user approves:
- "I'd like to monitor your sleep trends for 2 weeks" → approve/reject inline
- Approved NVs become scheduled thread events
- Trust level 2 agents can auto-schedule NVs without approval

---

## Part 4: Trust Negotiation In-Thread — Later Phase

- Agent proposals appear as interactive messages in threads
- Approve/reject inline in the conversation
- Trust escalation: "You've approved my last 10 proposals. Want me to run these automatically?"
- Trust is per-agent, per-capability, visible in the agent's profile

---

## Implementation Order (Treatment Plan)

| Visit | What | Scope |
|-------|------|-------|
| **1** | `AGENTS` knowledge category + profile `.md` generation | Loop Symphony only |
| **2** | Conductor reads profiles and injects into agent context | Loop Symphony only |
| **3** | Dispatch threads with participant lists | Dispatch only |
| **4** | Agent registration endpoint in Dispatch | Dispatch + Loop Symphony |
| **5** | Agent-to-agent message routing through Dispatch | Both |
| **6** | User lurk/intervene in agent threads | Dispatch UI |
| **7** | Agent profile UI in Dispatch | Dispatch UI |
| **8** | NV as thread events | Both |
| **9** | Trust negotiation in-thread | Both |

Each visit is independently shippable. Visit 1-2 can happen entirely in Loop Symphony without touching Dispatch. Visit 3 can happen in Dispatch without touching Loop Symphony. They converge at Visit 4-5.

---

## Key Design Decisions to Make Tomorrow

1. **Profile storage**: New knowledge category in existing system vs. separate file directory?
   - Recommendation: Use the existing knowledge layer. It already has markdown, categories, sources, per-user scoping.

2. **Token budget**: How many agent profiles to inject per request?
   - Recommendation: Start with "only agents whose capabilities are relevant to the current task." The conductor already does capability-based routing — extend that to profile selection.

3. **Profile update frequency**: After every interaction or batched?
   - Recommendation: After every cross-agent interaction. Lightweight append to interaction history section.

4. **Thread storage**: Where do threads live?
   - This is a Dispatch architecture question. Needs to support: participant list, message history, thread metadata, user read/unread state.

5. **Agent identity persistence**: How does an agent maintain consistent "personality" across conversations?
   - The profile IS the persistence mechanism. Inject it into every conversation. The agent reads its own profile and stays in character.

---

## Context for Tomorrow

- Loop Symphony is at Phase 5 complete, 950+ tests passing
- Conductor is singleton per server, routes to 5 instruments
- Knowledge layer has 5 categories (CAPABILITIES, BOUNDARIES, PATTERNS, CHANGELOG, USER)
- `KnowledgeEntry` model already supports: category, title, content (markdown), source, confidence, user_id, tags
- `KnowledgeSource` enum already has: SEED, ERROR_TRACKER, ARRANGEMENT_TRACKER, TRUST_TRACKER, MANUAL, SYSTEM, ROOM_LEARNING, AGGREGATED
- Instruments already have `ToolManifest` with name, description, capabilities, version
- Room registry already handles agent/room discovery and scoring
- Dispatch can receive from agents (production, works)
- Quest sends context and gets briefings (production, works)
