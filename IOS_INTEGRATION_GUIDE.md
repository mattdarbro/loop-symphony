# Loop Symphony iOS Integration Guide

> For iOS developers building apps that connect to the Loop Symphony server.
> Server version: Phase 5C (867 tests). Updated: 2026-02-10.

---

## 1. Architecture Overview

Loop Symphony is a distributed agentic framework. The **iOS Room** is the user-facing "Reception" — it knows the user (personality, preferences, history) and packages clean requests to the **Server Room** (the "Engine"), which orchestrates autonomous cognitive loops and returns structured results.

**Key principle: Each side knows its job and doesn't need the other's internals.**

| iOS Room Knows | iOS Room Does NOT Know |
|---|---|
| Who the user is (soul.md, preferences) | HOW the server solves problems |
| How to talk to them (voice, tone, personality) | What instruments exist |
| What they're asking for (intent extraction) | How loops work internally |
| How to package a clean request | Termination criteria details |
| When to handle things locally vs. escalate | |

The server returns **personality-agnostic results** — the iOS app wraps them in personality before presenting to the user.

---

## 2. Authentication

All authenticated endpoints use two HTTP headers:

```
X-Api-Key: <your-api-key>       # Required — identifies the app
X-User-Id: <external-user-id>   # Optional — identifies the user within the app
```

- The server validates the API key against registered apps in the database
- If `X-User-Id` is provided, the server auto-creates a user profile on first use
- Some endpoints require auth (`Auth`), others accept it optionally (`OptionalAuth`), and some don't need it at all

### Auth Levels in This Guide

- **Required** = must include `X-Api-Key`
- **Optional** = works without auth, but filters results by app/user when provided
- **None** = no auth needed

---

## 3. Core Task Flow

This is the primary interaction loop between iOS and the server.

### 3.1 Submit a Task

```
POST /task
Auth: Optional
```

**Request Body (`TaskRequest`):**

```json
{
  "id": "optional-uuid-or-auto-generated",
  "query": "What are the best hiking trails near Portland?",
  "context": {
    "app_id": null,
    "user_id": null,
    "conversation_summary": "User is planning a weekend trip to Oregon",
    "attachments": [],
    "location": "San Francisco, CA",
    "goal": "planning a trip",
    "intent": {
      "type": "research",
      "urgency": "planning",
      "success_criteria": "list of trails with difficulty ratings",
      "confidence": 1.0,
      "inferred": false
    }
  },
  "preferences": {
    "thoroughness": "balanced",
    "trust_level": 0,
    "notify_on_complete": true,
    "max_spawn_depth": null
  }
}
```

**Trust Levels (critical for iOS to manage):**

| Level | Name | Behavior |
|-------|------|----------|
| 0 | Supervised | Returns a **plan** for user approval before executing |
| 1 | Semi-autonomous | Executes immediately, returns detailed results |
| 2 | Autonomous | Executes immediately, minimal output |

**Response (`TaskSubmitResponse`):**

```json
// trust_level=0: Plan returned for approval
{
  "task_id": "abc-123",
  "status": "awaiting_approval",
  "message": "Task plan ready for approval. Call POST /task/{id}/approve to execute.",
  "plan": {
    "task_id": "abc-123",
    "query": "What are the best hiking trails near Portland?",
    "instrument": "research",
    "process_type": "semi_autonomic",
    "estimated_iterations": 5,
    "description": "Research hiking trails using web search and synthesis",
    "requires_approval": true
  }
}

// trust_level=1 or 2: Executes immediately
{
  "task_id": "abc-123",
  "status": "pending",
  "message": "Task submitted successfully",
  "plan": null
}
```

### 3.2 Approve a Plan (Trust Level 0 Only)

```
POST /task/{task_id}/approve
Auth: None
```

No request body. Returns `TaskSubmitResponse` with `status: "pending"`.

### 3.3 Poll for Results

```
GET /task/{task_id}
Auth: None
```

**While running** — returns `TaskPendingResponse`:
```json
{
  "task_id": "abc-123",
  "status": "running",
  "progress": "Task is running",
  "started_at": "2026-02-10T12:00:00Z"
}
```

**When complete** — returns `TaskResponse`:
```json
{
  "request_id": "abc-123",
  "outcome": "complete",
  "findings": [
    {
      "content": "Forest Park has 80+ miles of trails...",
      "source": "https://example.com/forest-park",
      "confidence": 0.95,
      "timestamp": "2026-02-10T12:00:05Z"
    }
  ],
  "summary": "Portland has excellent hiking options. Forest Park offers 80+ miles...",
  "confidence": 0.92,
  "metadata": {
    "instrument_used": "research",
    "iterations": 3,
    "duration_ms": 12500,
    "sources_consulted": ["https://example.com/forest-park", "..."],
    "process_type": "semi_autonomic",
    "room_id": "server",
    "failover_events": []
  },
  "discrepancy": null,
  "suggested_followups": [
    "What gear do I need for hiking in Oregon?",
    "[proactive] Consider checking trail conditions before your trip",
    "[education] Tip: The research instrument can perform deeper multi-source investigation"
  ]
}
```

### 3.4 Stream Events (SSE)

For real-time progress updates instead of polling:

```
GET /task/{task_id}/stream
Auth: None
Content-Type: text/event-stream
```

Events arrive as Server-Sent Events:

```
data: {"event": "started", "task_id": "abc-123", "timestamp": 1707566400}

data: {"event": "iteration", "task_id": "abc-123", "iteration_num": 1, "phase": "hypothesis", "data": {...}, "duration_ms": 2100, "timestamp": 1707566402}

data: {"event": "iteration", "task_id": "abc-123", "iteration_num": 2, "phase": "experiment", "data": {...}, "duration_ms": 3200, "timestamp": 1707566405}

data: {"event": "complete", "task_id": "abc-123", "outcome": "complete", "summary": "...", "confidence": 0.92, "timestamp": 1707566412}
```

Late joiners receive the full event history. The stream terminates after `complete` or `error`. Keepalive pings sent every 30s.

### 3.5 Cancel a Task

```
POST /task/{task_id}/cancel
Auth: None
```

Returns `{"status": "cancelling", "task_id": "abc-123"}`.

### 3.6 Get Checkpoints

```
GET /task/{task_id}/checkpoints
Auth: None
```

Returns the list of iteration records (useful for showing "what happened" detail).

---

## 4. Outcomes & How to Display Them

The server returns one of four outcomes. iOS should present each differently:

| Outcome | Meaning | iOS Presentation Hint |
|---------|---------|----------------------|
| `complete` | High confidence, task solved | Show summary confidently |
| `saturated` | Best answer available, no more to learn | Show summary with "best available" note |
| `bounded` | Hit limits, may need more resources | Show partial results + offer to continue |
| `inconclusive` | Conflicting signals detected | Show findings + `discrepancy` + `suggested_followups` |

**Task statuses** during execution: `pending` → `running` → `complete` or `failed`. Trust level 0 adds: `pending` → `awaiting_approval` → (approve) → `running` → `complete`.

---

## 5. Suggested Followups & Interventions

The `suggested_followups` field on `TaskResponse` contains two types of entries:

1. **Plain followups**: Regular suggestions like `"What gear do I need?"`
2. **Interventions** (prefixed): System-generated suggestions with a type tag

### Intervention Types

| Prefix | Type | Meaning |
|--------|------|---------|
| `[proactive]` | Proactive | Recurring pain point detected — suggests a solution |
| `[pushback]` | Pushback | Request was too broad — suggests narrowing scope |
| `[scoping]` | Scoping | Request has multiple parts — suggests breaking down |
| `[education]` | Education | Feature the user hasn't tried — gentle capability hint |

**iOS should parse these prefixes** and present interventions differently from regular followups (e.g., as system tips, info cards, or inline suggestions).

**Trust-level gating**: The server automatically filters interventions based on trust level:
- Level 0: All four types
- Level 1: No education (user knows the system)
- Level 2: Only proactive + pushback

---

## 6. Intent System

iOS can provide structured intent to help the server choose better strategies. If not provided, the server infers intent from the query (with lower confidence).

### Intent Types

| Type | Description | Server Strategy |
|------|-------------|-----------------|
| `decision` | Help me choose between options | Gathers options + tradeoffs |
| `research` | Help me understand something deeply | Deep multi-source investigation |
| `action` | Help me do something / get steps | Returns actionable steps |
| `curiosity` | Just wondering, no specific goal | Quick, direct answer |
| `validation` | Confirm or challenge what I think | Presents evidence + counterpoints |

### Urgency Levels

| Level | Description |
|-------|-------------|
| `immediate` | Need answer now |
| `soon` | Today or tomorrow |
| `planning` | Days/weeks out |
| `exploratory` | No time pressure |

**Providing intent from iOS is strongly recommended** — it makes the server 20-30% more effective at choosing the right approach.

---

## 7. Trust Escalation

The server tracks success metrics per app/user and suggests trust level upgrades.

### Get Current Metrics

```
GET /trust/metrics
Auth: Required
```

Returns:
```json
{
  "app_id": "uuid",
  "user_id": "uuid",
  "total_tasks": 25,
  "successful_tasks": 23,
  "failed_tasks": 2,
  "consecutive_successes": 8,
  "current_trust_level": 0,
  "last_task_at": "2026-02-10T12:00:00Z"
}
```

### Check for Upgrade Suggestion

```
GET /trust/suggestion
Auth: Required
```

Returns `TrustSuggestion` or `null`:
```json
{
  "current_level": 0,
  "suggested_level": 1,
  "reason": "5+ consecutive successes with 92% success rate",
  "metrics": { ... }
}
```

**iOS should periodically check this** and prompt the user: "You've had 8 successful tasks in a row. Want to enable semi-autonomous mode?"

### Update Trust Level

```
PUT /trust/level
Auth: Required
```

Body: `{"trust_level": 1}`

Upgrade rules (server-suggested):
- 0 → 1: 5+ consecutive successes, 80%+ success rate
- 1 → 2: 10+ consecutive successes, 90%+ success rate
- Downgrade: Always user-initiated (never automatic)

---

## 8. Knowledge System

The server maintains structured knowledge files that iOS can read and display.

### Knowledge Files

```
GET /knowledge/capabilities    # What the system can do
GET /knowledge/boundaries      # Known limitations
GET /knowledge/patterns        # Learned patterns from usage
GET /knowledge/changelog       # Recent changes
Auth: None
```

Each returns a `KnowledgeFile`:
```json
{
  "category": "capabilities",
  "title": "Capabilities",
  "markdown": "# Capabilities\n\n## Research\n- Can search the web...",
  "entries": [
    {
      "id": "uuid",
      "category": "capabilities",
      "title": "Web Research",
      "content": "Can search the web using Tavily...",
      "source": "seed",
      "confidence": 1.0,
      "tags": ["research", "web"],
      "is_active": true
    }
  ],
  "last_updated": "2026-02-10T12:00:00Z"
}
```

### Per-User Knowledge

```
GET /knowledge/user/{user_id}
Auth: None
```

Returns user-specific patterns, preferences, and history.

### Knowledge Sync (Room Protocol)

If the iOS app registers as a room (see Section 10), knowledge is synced automatically via heartbeat piggybacking:

1. iOS sends `last_knowledge_version` in its heartbeat
2. Server responds with delta entries since that version
3. iOS stores entries in a local cache for offline access

---

## 9. Heartbeats (Scheduled Tasks)

Heartbeats are recurring tasks that execute on a cron schedule.

### Create a Heartbeat

```
POST /heartbeats
Auth: Required
```

```json
{
  "name": "Morning Briefing",
  "query_template": "What are the top 3 news stories today, {date}?",
  "cron_expression": "0 7 * * *",
  "timezone": "America/Los_Angeles",
  "context_template": {},
  "webhook_url": null
}
```

### Other Heartbeat Endpoints

```
GET    /heartbeats                    # List all (auth required)
GET    /heartbeats/{id}              # Get one
PATCH  /heartbeats/{id}              # Update (partial)
DELETE /heartbeats/{id}              # Delete
POST   /heartbeats/tick              # Force execution check
GET    /heartbeats/status            # Execution status
```

---

## 10. Room Registration (iOS as a Room)

The iOS app can register as a Room to participate in cross-room orchestration and knowledge sync.

### Register

```
POST /rooms/register
Auth: None
```

```json
{
  "room_id": "ios-{device-uuid}",
  "room_name": "Matt's iPhone",
  "room_type": "ios",
  "url": "https://device-callback-url-or-push",
  "capabilities": ["camera", "microphone", "sensors", "notifications", "personality"],
  "instruments": []
}
```

### Heartbeat (with Knowledge Sync)

```
POST /rooms/heartbeat
Auth: None
```

```json
{
  "room_id": "ios-{device-uuid}",
  "status": "online",
  "capabilities": ["camera", "microphone", "sensors", "notifications", "personality"],
  "last_knowledge_version": 5
}
```

Response:
```json
{
  "status": "ok",
  "room_id": "ios-abc",
  "knowledge_updates": {
    "server_version": 8,
    "entries": [
      {
        "id": "entry-id",
        "category": "patterns",
        "title": "Common Research Patterns",
        "content": "...",
        "source": "error_tracker",
        "confidence": 0.8,
        "tags": ["learned"],
        "version": 7
      }
    ],
    "removed_ids": ["old-entry-id"]
  }
}
```

If no knowledge has changed, `knowledge_updates` will be `null`.

### Report Learnings

iOS can report observations back to the server for cross-room aggregation:

```
POST /knowledge/learnings
Auth: None
```

```json
{
  "room_id": "ios-abc",
  "learnings": [
    {
      "category": "patterns",
      "title": "User prefers concise answers",
      "content": "This user consistently dismisses long responses",
      "confidence": 0.7,
      "tags": ["user_preference"],
      "room_id": "ios-abc"
    }
  ]
}
```

### Deregister (on App Termination)

```
POST /rooms/deregister
Auth: None
Body: {"room_id": "ios-abc"}
```

---

## 11. Task Management

### Active Tasks

```
GET /tasks/active
Auth: Optional (filters by app when provided)
```

Returns list of currently running tasks — useful for "What are you working on?" UI.

### Recent Tasks

```
GET /tasks/recent?limit=20
Auth: Optional
```

### Task Stats

```
GET /tasks/stats
Auth: None
```

---

## 12. System Health

```
GET /health              # Quick check: {"status": "ok", "version": "..."}
GET /health/system       # Detailed: components, uptime, error tracking
GET /health/database     # Database connectivity
GET /rooms/status        # Room degradation status across the system
```

---

## 13. Complete Endpoint Reference

### Tasks
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/task` | Optional | Submit a task |
| POST | `/task/{id}/approve` | None | Approve a trust-level-0 plan |
| GET | `/task/{id}` | None | Get result or status |
| GET | `/task/{id}/stream` | None | SSE event stream |
| GET | `/task/{id}/checkpoints` | None | Iteration history |
| POST | `/task/{id}/cancel` | None | Cancel running task |
| GET | `/tasks/active` | Optional | Currently running tasks |
| GET | `/tasks/recent` | Optional | Recent task history |
| GET | `/tasks/stats` | None | Aggregate statistics |

### Advanced Task Submission
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/task/plan` | Optional | Get arrangement proposal |
| POST | `/task/plan/validate` | None | Validate an arrangement |
| POST | `/task/novel` | Optional | Submit with novel arrangement |
| POST | `/task/loop/propose` | None | Propose a new loop type |
| POST | `/task/loop/validate` | None | Validate a loop proposal |
| POST | `/task/loop/plan` | None | Get loop execution plan |
| POST | `/task/loop` | Optional | Submit a loop task |

### Arrangements
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/arrangements` | Optional | List saved arrangements |
| POST | `/arrangements` | Optional | Save an arrangement |
| GET | `/arrangements/{id}` | None | Get one arrangement |
| DELETE | `/arrangements/{id}` | None | Delete an arrangement |
| GET | `/arrangements/suggestion` | Optional | Get arrangement suggestion for query |
| POST | `/arrangements/from-task/{id}` | None | Save arrangement from completed task |

### Trust
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/trust/metrics` | Required | Current trust metrics |
| GET | `/trust/suggestion` | Required | Upgrade suggestion |
| PUT | `/trust/level` | Required | Update trust level |

### Knowledge
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/knowledge/capabilities` | None | Capabilities knowledge file |
| GET | `/knowledge/boundaries` | None | Boundaries knowledge file |
| GET | `/knowledge/patterns` | None | Patterns knowledge file |
| GET | `/knowledge/changelog` | None | Changelog knowledge file |
| GET | `/knowledge/user/{user_id}` | None | Per-user knowledge |
| POST | `/knowledge/entries` | None | Create manual entry |
| GET | `/knowledge/entries` | None | List entries (filter: `?category=&source=`) |
| POST | `/knowledge/refresh` | None | Refresh from trackers |
| POST | `/knowledge/learnings` | None | Accept room learnings |
| POST | `/knowledge/aggregate` | None | Aggregate learnings |
| GET | `/knowledge/sync/status` | None | Sync status for all rooms |

### Rooms
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/rooms/register` | None | Register a room |
| POST | `/rooms/deregister` | None | Deregister a room |
| POST | `/rooms/heartbeat` | None | Room heartbeat (+ knowledge sync) |
| GET | `/rooms` | None | List all rooms |
| GET | `/rooms/{id}` | None | Get room details |
| GET | `/rooms/status` | None | Degradation status |

### Heartbeats (Scheduled Tasks)
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/heartbeats` | Required | Create heartbeat |
| GET | `/heartbeats` | Required | List heartbeats |
| GET | `/heartbeats/{id}` | Required | Get heartbeat |
| PATCH | `/heartbeats/{id}` | Required | Update heartbeat |
| DELETE | `/heartbeats/{id}` | Required | Delete heartbeat |
| POST | `/heartbeats/tick` | Required | Force execution check |
| GET | `/heartbeats/status` | Required | Execution status |

### Interventions
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/interventions/status` | None | Engine status |
| POST | `/interventions/evaluate` | None | Dry-run evaluation |

### Health
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | None | Quick health check |
| GET | `/health/system` | None | Detailed system health |
| GET | `/health/database` | None | Database health |

---

## 14. Data Models Quick Reference

### Enums

```swift
// Outcome
enum Outcome: String { case complete, saturated, bounded, inconclusive }

// TaskStatus
enum TaskStatus: String { case pending, awaiting_approval, running, complete, failed }

// IntentType
enum IntentType: String { case decision, research, action, curiosity, validation }

// UrgencyLevel
enum UrgencyLevel: String { case immediate, soon, planning, exploratory }

// ProcessType
enum ProcessType: String { case autonomic, semi_autonomic, conscious }

// InterventionType
enum InterventionType: String { case proactive, pushback, scoping, education }

// KnowledgeCategory
enum KnowledgeCategory: String { case capabilities, boundaries, patterns, changelog, user }
```

### Core Models (Swift Codable)

```swift
struct TaskRequest: Codable {
    var id: String = UUID().uuidString
    let query: String
    var context: TaskContext?
    var preferences: TaskPreferences?
}

struct TaskContext: Codable {
    var appId: String?
    var userId: String?
    var conversationSummary: String?
    var attachments: [String] = []
    var location: String?
    var goal: String?
    var intent: Intent?
}

struct TaskPreferences: Codable {
    var thoroughness: String = "balanced"  // "quick", "balanced", "thorough"
    var trustLevel: Int = 0                // 0, 1, 2
    var notifyOnComplete: Bool = true
    var maxSpawnDepth: Int?
}

struct Intent: Codable {
    var type: IntentType = .curiosity
    var urgency: UrgencyLevel = .exploratory
    var successCriteria: String?
    var parentGoalId: String?
    var confidence: Double = 1.0
    var inferred: Bool = false
}

struct TaskSubmitResponse: Codable {
    let taskId: String
    let status: TaskStatus
    let message: String
    let plan: TaskPlan?
}

struct TaskPlan: Codable {
    let taskId: String
    let query: String
    let instrument: String
    let processType: String
    let estimatedIterations: Int
    let description: String
    let requiresApproval: Bool
}

struct TaskResponse: Codable {
    let requestId: String
    let outcome: Outcome
    let findings: [Finding]
    let summary: String
    let confidence: Double
    let metadata: ExecutionMetadata
    let discrepancy: String?
    let suggestedFollowups: [String]
}

struct Finding: Codable {
    let content: String
    let source: String?
    let confidence: Double
    let timestamp: String
}

struct ExecutionMetadata: Codable {
    let instrumentUsed: String
    let iterations: Int
    let durationMs: Int
    let sourcesConsulted: [String]
    let processType: ProcessType
    let roomId: String?
    let failoverEvents: [[String: AnyCodable]]  // or just [String: Any] via custom decoder
}

struct TaskPendingResponse: Codable {
    let taskId: String
    let status: TaskStatus
    let progress: String?
    let startedAt: String?
}
```

---

## 15. Recommended iOS Architecture

### Service Layer

```
LoopSymphonyClient
├── TaskService         (submit, poll, stream, cancel, approve)
├── TrustService        (metrics, suggestions, update)
├── KnowledgeService    (files, entries, user knowledge)
├── RoomService         (register, heartbeat, deregister, learnings)
├── HeartbeatService    (CRUD, scheduled tasks)
└── HealthService       (health checks)
```

### Key Implementation Notes

1. **JSON key strategy**: The server uses `snake_case`. Configure your `JSONDecoder` with `.convertFromSnakeCase`.

2. **SSE streaming**: Use `URLSession` with a streaming task or a library like `EventSource` for the `/task/{id}/stream` endpoint.

3. **Room heartbeat interval**: Send heartbeats every 60 seconds. The server marks rooms as offline after 120 seconds of silence.

4. **Knowledge cache**: Store synced knowledge entries in Core Data or a local SQLite DB. Track `server_version` locally so you only receive deltas.

5. **Intent extraction**: Invest in good local intent classification. The server can infer intent, but iOS-provided intent (with `inferred: false`) is more reliable.

6. **Personality wrapping**: The server's `summary` field is personality-agnostic. iOS should wrap it in the user's preferred personality/voice (from `soul.md`) before display.

7. **Intervention parsing**: Parse `suggested_followups` for `[type]` prefixes and render interventions as distinct UI elements (tips, cards, badges) rather than plain text.

8. **Offline handling**: When the server is unreachable, the iOS app should:
   - Queue tasks for later submission
   - Use cached knowledge for local context
   - Report learnings when connectivity resumes

9. **Error handling**: Server returns standard HTTP status codes:
   - 200: Success
   - 201: Created (heartbeats)
   - 400: Bad request
   - 401: Invalid API key
   - 403: App deactivated
   - 404: Not found
   - 500: Server error (check `detail` field)

---

## 16. Recommended Implementation Order

1. **Health check** — Verify server connectivity
2. **Task submission + polling** — Core flow (POST /task + GET /task/{id})
3. **SSE streaming** — Real-time progress
4. **Trust system** — Metrics + level management
5. **Room registration + heartbeat** — Join the room network
6. **Knowledge sync** — Cache knowledge locally via heartbeat piggybacking
7. **Intent extraction** — Provide structured intent with requests
8. **Intervention display** — Parse and present intervention followups
9. **Heartbeats** — Scheduled recurring tasks
10. **Learning reporting** — Report observations back to server
