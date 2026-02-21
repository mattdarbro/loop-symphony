# Loop Library

Pure loop methodology — instruments, compositions, and execution.

Zero dependencies on conductor, governance, trust, rooms, or personality.

## Structure

- `instruments/` — Base instrument + concrete implementations (note, research, synthesis, vision, falcon, magenta)
- `compositions/` — Sequential and parallel composition patterns
- `execution/` — Loop executor and proposer for custom loop specifications
- `termination/` — Termination evaluator for done-signal detection
- `models/` — Pydantic models (task, finding, outcome, arrangement, etc.)
- `tools/` — Tool protocol, Claude client, Tavily client, registry
- `symphonies/` — Named pre-built pipeline configurations

## Install

```bash
pip install -e .
# With web search support:
pip install -e ".[research]"
```
