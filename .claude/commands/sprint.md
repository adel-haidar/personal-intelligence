# /sprint — Parallel Work Session

Launch a structured parallel sprint across multiple personal-intelligence modules.

## Usage
```
/sprint <what you want to build>
```

## What this command does
1. Reads your sprint goal
2. Decomposes it into independent parallel tasks per module
3. Launches each task as a background subagent simultaneously
4. Synthesizes all results when complete

## Example prompts after /sprint
```
/sprint Add a weight trend chart to the health dashboard and expose a 
        GET /api/health/trend endpoint that returns the last 30 days

/sprint Refactor BankAdviser Stage 2 to use strict Pydantic contracts 
        and add the corresponding frontend card to show the stage output

/sprint Create the PULSE personas table, seed 3 personas, and add a 
        read-only feed view in Vue 3

/sprint Fix the email delta_link persistence bug and add a status indicator
        to the frontend dashboard
```

## Sprint Template (Claude will use this pattern)

When /sprint is invoked, dispatch these agents in parallel for tasks
that touch their domain. Always be explicit:

```
Use 3 parallel background subagents for this sprint:

1. @frontend-agent: [Frontend task — specific component/store/view to create/modify]
   Working path: frontend/src/[...]
   Expected output: [what the component should do]

2. @[module]-agent: [Backend task — specific file/function/endpoint to create/modify]
   Working path: src/personal_intelligence/[module]/[...]
   Expected output: [API contract or behavior]

3. @database-agent: [Schema task — new table or column needed]
   Working path: migrations/
   Expected output: [migration file name and what it adds]

When all three complete, synthesize the results and confirm:
- Backend endpoint matches the frontend API call
- Migration aligns with the model used in the backend
- No type mismatches between layers
```

## Agent Color Reference (for visual identification)
| Agent                  | Color  |
|------------------------|--------|
| frontend-agent         | Blue   |
| bank-adviser-agent     | Green  |
| health-agent           | Cyan   |
| memory-agent           | Purple |
| email-agent            | Orange |
| job-hunter-agent       | Yellow |
| auth-agent             | Red    |
| multi-agent-orchestrator | Pink |
| infra-agent            | Orange |
| database-agent         | Yellow |
| pulse-agent            | Pink   |
| signal-agent           | Cyan   |

## Notes
- infra-agent and auth-agent run in `permissionMode: default` — they will ask for confirmation.
- database-agent's DDL changes also require confirmation.
- All other agents use `permissionMode: acceptEdits` — they run autonomously.
- For overnight runs with tmux: add `--dangerously-skip-permissions` and set agents to `bypassPermissions` in their frontmatter temporarily.
