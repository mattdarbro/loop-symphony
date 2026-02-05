# Loop Symphony: Complete Build Phases

> Derived from PRD v2.0. Each numbered phase maps to the PRD's build plan.
> Lettered sub-phases are implementation steps within each numbered phase.
> Updated: 2026-02-04

---

## Current State

**Phase 1 Server Room: COMPLETE. Bridge A-E: COMPLETE. Phase 2A-2D, 2G-2I: COMPLETE.** 292 tests passing.

| Component | Status | Notes |
|-----------|--------|-------|
| FastAPI + routes | Done | POST /task, GET /task/{id}, GET /health |
| TaskRequest / TaskResponse | Done | Full contract per PRD Section 5 |
| Supabase DatabaseClient | Done | tasks + task_iterations tables |
| Termination Evaluator | Done | Confidence, saturation, bounds (PRD 6.2) |
| Note instrument | Done | Atomic single-cycle (PRD 8.1) |
| Research instrument | Done | Iterative scientific method loop (PRD 8.1) |
| Discrepancy detection | Done | Contradiction detection + severity analysis |
| Four-state outcomes | Done | COMPLETE, SATURATED, BOUNDED, INCONCLUSIVE (PRD 6.1) |
| Conductor | Done | Routing + optional registry-based tool injection |
| ClaudeClient | Done | Retry, Tool protocol, manifest, capabilities: {reasoning, synthesis, analysis} |
| TavilyClient | Done | Parallel search, Tool protocol, manifest, capabilities: {web_search} |
| Tool protocol + manifests | Done | Phase A — runtime-checkable Protocol, ToolManifest |
| Instrument protocol | Done | Phase B — required/optional capabilities, tool injection via kwargs |
| Tool registry | Done | Phase C — ToolRegistry, CapabilityError, resolve() |
| Conductor registry integration | Done | Phase D — _build_instrument() with capability resolution |
| Synthesis instrument | Done | Phase 2B — merges multiple InstrumentResults, contradiction detection |
| Sequential composition | Done | Phase 2C — SequentialComposition pipeline, InstrumentConfig parameterization |
| Parallel composition | Done | Phase 2D — ParallelComposition fan-out/fan-in, timeout, partial failure |
| Vision instrument | Done | Phase 2A — VisionInstrument, complete_with_images, image routing |
| Process visibility types | Done | Phase 2G — ProcessType enum (AUTONOMIC, SEMI_AUTONOMIC, CONSCIOUS) |
| Checkpoint emission | Done | Phase 2H — checkpoint_fn callback, GET /task/{id}/checkpoints |
| SSE streaming | Done | Phase 2I — EventBus, GET /task/{id}/stream, late-joiner history replay |
| Test suite | Done | 292 tests passing |
| Registry in production path | Done | Phase E — routes.py creates ToolRegistry, passes to Conductor |
| Deployment | Not done | No Dockerfile, no Railway config |

### PRD Phase 2 items already shipped

The PRD places four-state termination and discrepancy detection in Phase 2 (Weeks 5-6).
Both were implemented during Phase 1 and are fully tested. Phase 2 work begins at the
composition and new-instrument level.

### Architecture patterns established (Bridge A-D)

Adding a **new tool**: implement Tool protocol, declare capabilities, register in ToolRegistry.

Adding a **new instrument**: subclass BaseInstrument, declare required/optional capabilities,
accept injected tools via kwargs, add branch in Conductor._build_instrument(), add routing logic.

These patterns were not in the PRD but emerged from the bridge work. All Phase 2+
instruments and tools follow them.

---

## Phase 1: Foundation -- COMPLETE

> PRD Weeks 1-4. Establish iOS <-> Server core interaction with basic loop execution.

### Server Room (Weeks 1-2) -- COMPLETE

All items done. See Current State table above.

### 1A: Deploy to Railway

> Last Server Room deliverable for Phase 1. Can run in parallel with Phase E.

- [ ] Create `Dockerfile` (Python 3.11+, uvicorn)
- [ ] Create `railway.toml` with deploy config
- [ ] Create `.dockerignore`
- [ ] Environment variable documentation for Railway
- [ ] Verify health endpoint works after deploy
- [ ] Smoke test: POST /task from curl, poll GET /task/{id}

**Verify:** `curl https://<deployed-url>/health` returns 200 with version.

### 1B-1E: iOS Room (Weeks 3-4) -- SEPARATE DISCIPLINE

> These happen in the iOS project, not this server repo.

- [ ] 1B: Swift package structure + LoopSymphonyClient
- [ ] 1C: Basic intent extraction (local vs server decision)
- [ ] 1D: soul.md loader + personality configuration
- [ ] 1E: Response wrapping with personality + end-to-end test

---

## Bridge: Architecture Hardening (Phase A-D) -- COMPLETE

> Sat between Phase 1 and Phase 2. Hardened server internals so Phase 2
> features (new instruments, composition, parameterization) can be added
> without rewiring everything. No external behavior changes.

### Phase A: Tool Protocol -- COMPLETE

Added `Tool` protocol, `ToolManifest`, `health_check()`, and capability
declarations to `ClaudeClient` and `TavilyClient`.

**Files changed:** `tools/base.py` (new), `tools/claude.py`, `tools/tavily.py`
**Tests added:** `test_tool_protocol.py` (20 tests)

### Phase B: Instrument Protocol -- COMPLETE

Added `required_capabilities` / `optional_capabilities` to `BaseInstrument`.
Added keyword-arg tool injection to `NoteInstrument` and `ResearchInstrument`.
Zero-arg construction preserved for backward compat.

**Files changed:** `instruments/base.py`, `instruments/note.py`, `instruments/research.py`
**Tests added:** `test_instrument_protocol.py` (24 tests)

### Phase C: Tool Registry -- COMPLETE

Central registry that maps capabilities to tool instances. `ToolRegistry` with
`register()`, `get_by_name()`, `get_by_capability()`, `resolve(required, optional)`,
`health_check_all()`. Raises `CapabilityError` for missing required capabilities.

**Files created:** `tools/registry.py`, `tests/test_tool_registry.py` (22 tests)

### Phase D: Conductor Integration -- COMPLETE

Conductor accepts optional `ToolRegistry`. When provided, `_build_instrument(name)`
resolves capabilities via registry and injects tools. Zero-arg `Conductor()` still works.

**Files changed:** `manager/conductor.py`
**Tests added:** `tests/test_conductor_registry.py` (8 tests)

---

## Phase E: Wire Registry into Production -- COMPLETE

> The registry is now wired into the production path. `get_conductor()` creates a
> `ToolRegistry`, registers `ClaudeClient` and `TavilyClient`, and passes
> `registry=registry` to `Conductor()`. The health endpoint includes registered
> tool names when the registry is initialized.

- [x] Modify `get_conductor()` in `api/routes.py`:
  - Create `ToolRegistry`
  - Register `ClaudeClient()` and `TavilyClient()`
  - Pass `registry=registry` to `Conductor()`
- [x] Health endpoint includes registered tool names when registry is initialized
- [x] Tests: verify production conductor path uses registry (13 tests)

**Files changed:** `api/routes.py`
**Tests added:** `tests/test_routes_registry.py` (13 tests)

---

## Phase 2: Intelligence

> PRD Weeks 5-8. New instruments, composition patterns, process visibility.
>
> Note: PRD lists four-state termination and discrepancy detection here.
> Both are already shipped (Phase 1). Phase 2 begins at new instruments.

### Architectural decisions for Phase 2

**Synthesis input problem.** `BaseInstrument.execute(query, context)` takes a string query.
The SynthesisInstrument needs `InstrumentResult[]` as input. Solution: add an optional
`input_results: list[dict] | None = None` field to `TaskContext`. Compositions populate it.
The `execute()` signature stays unchanged.

**Circular import avoidance.** Compositions and nested sub-loops need to invoke instruments
through the Conductor, but instruments must not import the Conductor. Solution: the Conductor
passes callbacks (e.g., `spawn`, `checkpoint`) into the execution context at runtime. No
static circular imports.

**Parameterization merged into composition.** `InstrumentConfig` is a dataclass for runtime
tuning (override max_iterations, confidence thresholds). It is delivered as part of
composition specs, not as a standalone phase.

### 2A: Vision Instrument -- COMPLETE

> PRD 8.1: Extract information from images. Up to 3 iterations.

- [x] Add `complete_with_images(prompt, images, system)` to `ClaudeClient`
  - `ImageInput` dataclass for base64 and URL image sources
  - Builds multimodal content blocks for Claude API
  - Same retry logic as `complete()`; existing `complete()` unchanged
- [x] Add `"vision"` to `ClaudeClient.capabilities` and update manifest
- [x] Create `instruments/vision.py` with `VisionInstrument`
  - `required_capabilities = frozenset({"reasoning", "vision"})`
  - `max_iterations = 3`, TerminationEvaluator for confidence/saturation/bounds
  - `parse_attachments()` — data URI and HTTPS URL parsing
  - Scientific method: analyze image → extract findings as JSON → refine → synthesize
  - Checkpoint emission, no-image fallback (BOUNDED)
- [x] Add `"vision"` branch to `Conductor._build_instrument()`
- [x] Add vision routing logic (`_has_image_attachments`) — routes when image attachments present
- [x] Register in `instruments/__init__.py` and `tools/__init__.py` (ImageInput)
- [x] Tests: `test_vision.py` (30 tests across 6 classes) + updated existing tests

**Files created:** `instruments/vision.py`, `tests/test_vision.py`
**Files modified:** `tools/claude.py`, `tools/__init__.py`, `instruments/__init__.py`,
`manager/conductor.py`, `tests/test_conductor.py`, `tests/test_conductor_registry.py`,
`tests/test_routes_registry.py`, `tests/test_composition.py`, `tests/test_process_types.py`

**Depends on:** Phase E
**Independent of:** 2B, 2G, 2H (can run in parallel)

### 2B: Synthesis Instrument -- COMPLETE

> PRD 8.1: Combine inputs from multiple instruments into coherent output.

- [x] Add `input_results: list[dict] | None = None` to `TaskContext`
- [x] Create `instruments/synthesis.py` with `SynthesisInstrument`
  - `required_capabilities = frozenset({"reasoning", "synthesis"})`
  - `max_iterations = 2` (re-synthesize once if confidence low)
  - Confidence-weighted merging, contradiction detection, re-synthesis on low confidence
- [x] Add branch to `Conductor._build_instrument()`
- [x] Register in `instruments/__init__.py`
- [x] Tests: `test_synthesis.py` (24 tests across 6 classes)

**Files created:** `instruments/synthesis.py`, `tests/test_synthesis.py`
**Files modified:** `models/task.py`, `instruments/__init__.py`, `manager/conductor.py`,
`tests/test_conductor.py`, `tests/test_conductor_registry.py`, `tests/test_routes_registry.py`

### 2C: Sequential Composition + Parameterization -- COMPLETE

> PRD 8.2 + 7.2 Level 3. Pipeline execution with per-step tuning.

- [x] Create `models/instrument_config.py` with `InstrumentConfig`
  - `max_iterations: int | None = None`
  - `confidence_threshold: float | None = None`
  - `confidence_delta_threshold: float | None = None`
- [x] Create `manager/composition.py` with `SequentialComposition`
  - Constructor: ordered list of `(instrument_name, InstrumentConfig | None)` steps
  - `execute(query, context, conductor)` -- runs steps in order
  - Each step's output becomes `context.input_results` for the next step
  - Early termination if any step returns INCONCLUSIVE
  - Aggregates metadata (total iterations, all sources, total duration)
  - Helpers: `_serialize_result`, `_build_step_context`, `_apply_config`/`_restore_config`
- [x] Conductor gains `execute_composition(composition, request)` method
  - Duck-typed composition parameter (avoids circular imports)
- [x] Tests: `test_composition.py` (25 tests across 7 classes)

**Files created:** `models/instrument_config.py`, `manager/composition.py`, `tests/test_composition.py`
**Files modified:** `manager/conductor.py`, `manager/__init__.py`

### 2D: Parallel Composition -- COMPLETE

> PRD 8.2: Fan-out / fan-in. Multiple instruments test competing hypotheses.

- [x] Add `ParallelComposition` to `manager/composition.py`
  - Fan-out: launch N instruments via `asyncio.gather(return_exceptions=True)`
  - Fan-in: collect successful results, pass to merge instrument (default: synthesis)
  - Timeout: `asyncio.wait_for()` per branch, configurable via `timeout_seconds`
  - Partial failure: successful branches synthesized, failed branches noted in discrepancy
  - All-fail: returns INCONCLUSIVE with failure details
  - Design: branches as `list[str]` (not tuples) to avoid race conditions with shared instances
- [x] Tests: `test_composition_parallel.py` (17 tests across 5 classes)
  - Construction, parallel execution, timeout, partial failure, metadata aggregation

**Files modified:** `manager/composition.py`, `manager/__init__.py`
**Files created:** `tests/test_composition_parallel.py`

**Depends on:** 2B (synthesis for fan-in), 2C (shares composition.py and execute_composition)

### 2F: Nested Sub-loops

> PRD 8.2: A loop can spawn sub-loops. Bounded depth (default max 3).

- [ ] Add to `TaskContext`: `depth: int = 0`, `max_depth: int = 3`
- [ ] Conductor provides `spawn(sub_query, sub_context) -> InstrumentResult` callback
  - Increments depth, checks max_depth, raises `DepthExceededError` if exceeded
  - Executes sub-task through the normal conductor path
- [ ] Instruments receive spawn callback via execution context (not import)
- [ ] Tests: nested execution, depth limiting, result propagation

**Depends on:** 2C (shares the callback-injection pattern)
**Highest complexity in Phase 2.** Should be last.

### 2G: Process Visibility Types -- COMPLETE

> PRD Section 4: Autonomic, Semi-Autonomic, Conscious.

- [x] Create `models/process.py` with `ProcessType` enum
  - `AUTONOMIC`, `SEMI_AUTONOMIC`, `CONSCIOUS`
- [x] Conductor assigns process type:
  - Note queries -> AUTONOMIC
  - Research -> SEMI_AUTONOMIC
  - Compositions -> CONSCIOUS
  - Unknown instruments default to SEMI_AUTONOMIC
- [x] Add `process_type` to `ExecutionMetadata` (default AUTONOMIC for backward compat)
- [x] Tests: `test_process_types.py` (12 tests across 4 classes)

**Files created:** `models/process.py`, `tests/test_process_types.py`
**Files modified:** `models/finding.py`, `manager/conductor.py`

**Note:** Error communication verbosity (mentioned in BUILD_PHASES) deferred to Phase 3 when error patterns and trust levels are in play.

### 2H: Checkpoint Emission -- COMPLETE

> PRD Phase 2: Passive monitoring of in-progress tasks.
> Note: `DatabaseClient.record_iteration()` and `get_task_iterations()` already
> existed but were never called. This phase wires them in.

- [x] Add `checkpoint_fn` to `TaskContext` (excluded from serialization, runtime-only callback)
- [x] `execute_task_background()` creates closure binding `db.record_iteration()` to task_id
- [x] ResearchInstrument emits checkpoint at each iteration (with try/except for resilience)
- [x] Add `GET /task/{id}/checkpoints` endpoint (calls existing `get_task_iterations()`)
- [x] Tests: `test_checkpoints.py` (15 tests across 4 classes)

**Files created:** `tests/test_checkpoints.py`
**Files modified:** `models/task.py`, `instruments/research.py`, `api/routes.py`

**Design:** Checkpoint callback injected via `TaskContext.checkpoint_fn` at runtime.
Forward-compatible with Phase 2F `spawn` callback (same pattern).

### 2I: Streaming Support -- COMPLETE

> PRD Phase 2: Real-time streaming for conscious processes.

- [x] `api/events.py` — EventBus: in-memory per-task event pub/sub with history replay
- [x] SSE endpoint: `GET /task/{id}/stream` using `StreamingResponse`
- [x] `asyncio.Queue` per subscriber, pre-populated with history for late joiners
- [x] Events: started, iteration, complete, error (with terminal event detection)
- [x] 30s keepalive comments for proxy timeout prevention
- [x] Cleanup on client disconnect (unsubscribe) + TTL-based stale cleanup
- [x] `execute_task_background` emits events alongside DB writes
- [x] Tests: 28 new tests (EventBus emit/subscribe/terminal/cleanup, SSE endpoint, background events)

**Files:**
- `api/events.py` — NEW: EventBus, event type constants
- `api/routes.py` — MODIFIED: event_bus singleton, emit in background exec, SSE endpoint
- `api/__init__.py` — MODIFIED: export EventBus
- `tests/test_streaming.py` — NEW: 28 tests
- `tests/test_checkpoints.py` — MODIFIED: updated 3 tests for new signature

**Depends on:** 2H (checkpoints provide the event source)

### Phase 2 Priority Order

Fastest path to demonstrable multi-step intelligence:

| Priority | Phase | Description | Effort |
|----------|-------|-------------|--------|
| 1 | **E** | Wire registry into production | Small |
| 1 | **1A** | Deploy to Railway | Small |
| 2 | **2B** | Synthesis Instrument | Medium |
| 2 | **2G** | Process Types | Small |
| 2 | **2H** | Checkpoints | Medium |
| 3 | **2A** | Vision Instrument | Medium |
| 3 | **2C** | Sequential Composition + Parameterization | Large |
| 4 | **2D** | Parallel Composition | Medium |
| 4 | **2I** | Streaming | Medium |
| 5 | **2F** | Nested Sub-loops | Large |

**Minimum viable Phase 2:** E + 2B + 2C + 2G. This gives: registry in production, synthesis
instrument, sequential composition (research -> synthesis pipeline), and process type labeling.

### Phase 2 Verification

```bash
python3 -m pytest tests/ -v
```

**Phase 2 complete when (PRD 12.2):**
- [x] All four outcome states properly detected and communicated (done in Phase 1)
- [x] Inconclusive outcomes include discrepancy and suggestions (done in Phase 1)
- [ ] Sequential and parallel composition work reliably
- [ ] Streaming works for conscious processes
- [ ] Trust levels affect behavior as specified (deferred to 3D)

---

## Phase 3: Autonomy

> PRD Weeks 9-12. Manager creativity, trust escalation, background processing.

### How the bridge architecture helps Phase 3

- **Novel arrangements (3A-3B):** An arrangement is a serializable composition spec:
  `list[(instrument_name, InstrumentConfig)]` + composition type (sequential/parallel).
  The registry validates proposals via `resolve()` — "registered tools only" constraint
  from PRD 7.3 maps directly. Claude can be given `registry.get_all()` manifests as
  context when generating arrangements.
- **Meta-learning (3C):** Successful arrangements are persisted as JSON composition specs
  to a DB table, not as code. Loaded on startup and registered as named compositions.
  The composition system (2C/2D) provides the execution layer.
- **Autonomic monitoring (3E):** `registry.health_check_all()` is already built and async.
  The autonomic layer is a scheduler that calls it periodically.

### 3A: Novel Arrangement Generation

> PRD 7.2 Level 4: Manager creates new compositions not explicitly designed.

- [ ] Claude analyzes task and proposes arrangement as structured JSON
  - Given: list of available tool manifests (from `registry.get_all()`)
  - Given: list of available instrument names and their capabilities
  - Returns: composition spec (sequential/parallel, instrument names, configs)
- [ ] Conductor validates proposal via `registry.resolve()` for each instrument
- [ ] Execute validated arrangement via `execute_composition()`
- [ ] Arrangements must follow scientific method structure
- [ ] Must have explicit termination criteria

**Depends on:** 2C, 2D (composition system)

### 3B: Loop Proposal System

> PRD 7.2 Level 5: Propose entirely new loop specs when existing instruments don't fit.

- [ ] Proposal model: name, description, phases, termination criteria, required capabilities
- [ ] Constraint validation: scientific method structure required, bounds required
- [ ] Trust Level 0: human approval required before execution
- [ ] Trust Level 2: auto-execute with logging

**Depends on:** 3A, 3D (trust system)

### 3C: Meta-Learning

> PRD 7.4: Save successful novel arrangements as named instruments.

- [ ] Track arrangement success rates (outcome, confidence, user feedback)
- [ ] Suggest saving high-performing arrangements
- [ ] Persist as JSON composition specs to DB (not code)
- [ ] Load saved arrangements on startup, register as named compositions

**Depends on:** 3A

### 3D: Trust Escalation System

> PRD Section 9: Brilliant new employee model.
> Note: `TaskPreferences.trust_level` field already exists (0-2) but is unused.

- [ ] Wire `trust_level` into Conductor execution path:
  - Level 0: Return proposed plan before executing, wait for approval
  - Level 1: Auto-execute, return results with summary for review
  - Level 2: Full autonomy, only critical errors surface
- [ ] Trust level interacts with process type (2G)
- [ ] Trust can escalate over time based on success patterns

**Depends on:** 2G (process types)

### 3E: Autonomic Process Layer

> PRD 4.1: Heartbeat, compaction, token refresh. Invisible to user.
> Note: `registry.health_check_all()` is already built. This phase
> adds the scheduler that calls it.

- [ ] Background scheduler using FastAPI lifespan events (already in `main.py`)
- [ ] Periodic `health_check_all()` via registry
- [ ] Supabase connection monitoring
- [ ] Only surfaces on critical error ("pain response")

**Depends on:** Phase E (registry in production)

### 3F: Semi-Autonomic Process Layer

> PRD 4.1: Background research, scheduled tasks. Automatic but overridable.

- [ ] Background task queue (beyond FastAPI's BackgroundTasks)
- [ ] Scheduled task support
- [ ] User can query: "What are you working on?"
- [ ] User can cancel or redirect

**Depends on:** 3E, 2H (checkpoints for status visibility)

### 3G: Compaction Strategies

> PRD 10.3: Context management for long-running operations.

- [ ] Summarization: chunk -> summarize -> merge
- [ ] Pruning: score findings by relevance, drop bottom N%
- [ ] Selective: mark "must keep" vs "can compress"
- [ ] Strategy selection based on context type

**Independent.** Needed when compositions accumulate large findings lists.

### 3H: Error Learning

> PRD 10.2: Error pattern detection and institutional knowledge.

- [ ] Error classification taxonomy
- [ ] Error logging with learning context
- [ ] Pattern detection across errors
- [ ] Suggested approach adjustments based on patterns

**Independent.**

### 3I: Notification Layer

- [ ] Telegram integration for task completion
- [ ] Push notification support
- [ ] Configurable per-user notification preferences

**Independent.**

### Phase 3 Verification

**Phase 3 complete when (PRD 12.3):**
- [ ] Manager can propose and execute novel arrangements
- [ ] Background tasks run invisibly until complete
- [ ] Autonomic processes only surface on critical errors
- [ ] Error patterns are logged and learning suggestions made

---

## Phase 4: Local Room

> PRD Weeks 13-16. Edge computing, offline capability, privacy-sensitive processing.
> Note: The Tool protocol and ToolRegistry extend naturally to local tools.
> A local LLM (Ollama) would implement the Tool protocol with capabilities
> like {"reasoning"} and register in a local ToolRegistry.

### 4A: Local Room Foundation

- [ ] Local LLM integration (Ollama / LM Studio) implementing Tool protocol
- [ ] Room registration protocol with Server
- [ ] Basic Note instrument (local execution via local registry)
- [ ] File access tools (implement Tool protocol)

### 4B: Offline & Privacy

- [ ] Offline fallback when server unreachable
- [ ] Privacy-sensitive task routing (stays local)
- [ ] Escalation to Server for complex tasks
- [ ] Heartbeat and state synchronization

### 4C: Cross-Room Integration

- [ ] Manager routing across iOS, Server, Local
- [ ] Parallel room execution (iOS camera + Server search)
- [ ] Graceful degradation when rooms offline
- [ ] Room capability discovery (mDNS or central registry)

### Phase 4 Verification

**Phase 4 complete when (PRD 12.4):**
- [ ] Local room handles simple queries offline
- [ ] Privacy-sensitive tasks stay local
- [ ] Manager routes across all three rooms appropriately
- [ ] System degrades gracefully when rooms go offline

---

## Phase 5: Knowledge Layer

> PRD Weeks 17-18. Learnable knowledge layer for user guidance.

### 5A: Knowledge File System

- [ ] Implement `capabilities.md` -- what the system can do
- [ ] Implement `boundaries.md` -- what it can't do, with alternatives
- [ ] Implement `patterns.md` -- common user patterns and interventions
- [ ] Implement `changelog.md` -- what's new
- [ ] Implement `user/{id}.md` -- per-user learned patterns

### 5B: Knowledge Sync

- [ ] Server pushes knowledge updates to iOS rooms
- [ ] iOS syncs user-specific learnings back to Server
- [ ] Server aggregates cross-user patterns into global patterns.md

### 5C: Four Interventions

> PRD 13.3: Proactive suggestions, pushback, scoping, capability education.

- [ ] Proactive suggestion engine (detect recurring pain points)
- [ ] Pushback on unrealistic requests (redirect to achievable)
- [ ] Scoping for overwhelming requests (break down)
- [ ] Capability education (gentle feature discovery)

### Phase 5 Verification

**Phase 5 complete when (PRD 12.5):**
- [ ] Knowledge files synced between Server and iOS
- [ ] iOS proactively suggests solutions to detected pain points
- [ ] iOS pushes back on unrealistic requests with alternatives
- [ ] iOS helps scope overwhelming requests
- [ ] Capability education happens naturally in conversation

---

## Phase 6: Future (TBD)

- [ ] Robotics Room integration
- [ ] Advanced meta-learning
- [ ] Multi-user / multi-personality support
- [ ] FixionMail integration (writing room as personality)

---

## Dependency Graph

```
Phase 1 (Foundation) ..................... DONE
  |
  v
Bridge A-D (Architecture Hardening) ..... DONE
  |  A: Tool Protocol ................... DONE
  |  B: Instrument Protocol ............. DONE
  |  C: Tool Registry ................... DONE
  |  D: Conductor Integration ........... DONE
  |
  v
Phase E: Wire Registry into Production .. DONE
  |
  +----> 1A: Deploy to Railway (parallel, independent)
  |
  +----> 2G: Process Types (independent)
  |
  +----> 2H: Checkpoints (independent)
  |         |
  |         v
  |       2I: Streaming
  |
  +----> 2A: Vision Instrument (independent)
  |
  +----> 2B: Synthesis Instrument (independent)
  |         |
  |         v
  |       2C: Sequential Composition + Parameterization
  |         |
  |         +---> 2D: Parallel Composition
  |         |
  |         +---> 2F: Nested Sub-loops (last, highest complexity)
  |
  v
Phase 3 (Autonomy)
  |  3A: Novel Arrangements ............ blocked by 2C, 2D
  |  3B: Loop Proposals ................ blocked by 3A, 3D
  |  3C: Meta-Learning ................. blocked by 3A
  |  3D: Trust Escalation .............. blocked by 2G
  |  3E: Autonomic Layer ............... blocked by E (health checks built)
  |  3F: Semi-Autonomic Layer .......... blocked by 3E, 2H
  |  3G: Compaction .................... independent
  |  3H: Error Learning ................ independent
  |  3I: Notifications ................. independent
  |
  v
Phase 4 (Local Room) -- can start after Phase 2
  |
  v
Phase 5 (Knowledge Layer) -- requires Phase 3
  |
  v
Phase 6 (Future)
```

---

## Quick Reference: What's Next

1. ~~**Phase E** -- Wire registry into `api/routes.py`~~ DONE
2. **1A** -- Deploy to Railway (independent)
3. ~~**2B** -- Synthesis Instrument~~ DONE
4. ~~**2C** -- Sequential Composition + Parameterization~~ DONE
5. ~~**2G** -- Process Types~~ DONE
6. ~~**2H** -- Checkpoints~~ DONE
7. ~~**2D** -- Parallel Composition~~ DONE
8. ~~**2A** -- Vision Instrument~~ DONE
9. ~~**2I** -- Streaming~~ DONE
10. **2F** -- Nested Sub-loops (last, highest complexity)
