---
name: problem-solving
description: Framework for analyzing complex problems or incidents using OODA, FTA, etc.
---

# Problem-Solving Framework

Use this prompt when analyzing complex problems or incidents.

## Framework Selection Matrix

| Scenario                    | Primary Framework    | Secondary           | Rationale                                  |
| --------------------------- | -------------------- | ------------------- | ------------------------------------------ |
| Complex unknown incident    | Fishbone -> FTA      | 5 Whys              | Brainstorm -> map factors -> causal chains |
| Production incident (known) | Runbook              | OODA (if fails)     | Fast MTTR, escalate if novel               |
| Production incident (novel) | OODA -> FTA + 5 Whys | Runbook update      | Adapt -> analyze -> prevent -> document    |
| High-risk deployment        | Pre-Mortem -> OODA   | Runbook creation    | Identify risks -> plan -> create procedure |
| Simple known failure        | Runbook              | Issue (if missing)  | Fast recovery, document gap                |
| Process/human failure       | 5 Whys               | Issue               | Understand breakdown -> prevent            |
| Multi-factor system failure | FTA + 5 Whys         | Issue               | Comprehensive + actionable                 |
| Time-critical recovery      | Runbook -> OODA      | FTA + 5 Whys (post) | Recover first, analyze later               |

## OODA Loop (Observe-Orient-Decide-Act)

Use for: Unknown/evolving problems, incomplete information, time-critical decisions.

**Observe**: Gather facts without interpretation

- Logs, metrics, git history
- Error messages, system state
- Timeline, what changed

**Orient**: Analyze and synthesize

- Re-examine assumptions when facts contradict hypothesis
- Apply mental models: architecture, failure modes, dependencies
- Formulate hypotheses about root cause

**Decide**: Select course of action

- Evaluate options against constraints
- Consider blast radius and rollback complexity
- Document rationale

**Act**: Execute with validation

- Implement with monitoring
- Validate against success criteria
- Loop back to Observe if issues persist

## Fault Tree Analysis (FTA)

Use for: Complex failures with multiple potential causes, need to identify ALL factors.

**Method**:

1. Define top event (the failure)
2. Identify immediate causes (AND/OR gates)
3. Decompose each cause until reaching root causes
4. Identify contributing factors
5. Calculate critical paths

**Output**: Visual tree diagram, all contributing factors documented.

## 5 Whys Methodology

Use for: Understanding causal chains, human/process failures, simpler incidents.

**Method**:

1. State problem
2. Ask "Why did this happen?"
3. Ask "Why?" for each answer
4. Repeat until root cause reached (typically 5 iterations)
5. Verify by working backwards

**Output**: Causal chain, preventive measures at each level.

## Fishbone Diagram (Ishikawa)

Use for: Root cause unclear, team-based analysis, categorizing potential causes.

**Categories**: People, Process, Technology, Environment, Tools, Data

**Method**:

1. Define problem
2. Identify categories
3. Brainstorm causes per category
4. Prioritize for deeper analysis (FTA/5 Whys)

**Output**: Categorized cause list feeding into FTA analysis.

## Pre-Mortem Analysis

Use for: BEFORE deploying changes, high-risk changes, preventing incidents.

**Method**:

1. Assume failure: "This deployment failed catastrophically. Why?"
2. Brainstorm failure scenarios
3. Identify preventive measures
4. Implement safeguards
5. Document in runbook

**Output**: Preventive measures implemented BEFORE deployment.

## Runbook-Driven Troubleshooting

Use for: Known failure modes, operational incidents, time-critical recovery.

**Method**:

1. Identify failure mode
2. Follow documented procedure
3. Validate after each step
4. Escalate if off-script
5. Document gaps found

**Output**: Faster MTTR, consistent response, data for later RCA.

## Combination Strategies

**Complex Unknown Incident**:
Fishbone (15-30 min) -> FTA (30-60 min) -> 5 Whys (15-30 min per path) -> Issue

**Production Incident (Known)**:
Runbook (5-15 min) -> Issue if missing -> Update runbook

**Production Incident (Novel)**:
Runbook attempt -> OODA if fails -> FTA + 5 Whys post-incident -> Issue -> Runbook update

**High-Risk Deployment**:
Pre-Mortem (30-60 min) -> OODA (30-60 min) -> Runbook creation -> FTA + 5 Whys if failure
