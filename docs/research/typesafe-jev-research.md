# TypeSafe AI & Jev: A Comprehensive Research Paper

**Author:** Research Analysis  
**Date:** October 2026  
**Subject:** Deep technical analysis of TypeSafe AI's Jev model, the first System One model

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Company Background](#2-company-background)
3. [The System One Model Category](#3-the-system-one-model-category)
4. [Jev: Technical Specifications](#4-jev-technical-specifications)
5. [The Three Primitives](#5-the-three-primitives)
6. [Training Methodology: RLCD](#6-training-methodology-rlcd)
7. [Confidence & Calibration System](#7-confidence--calibration-system)
8. [API & SDK Reference](#8-api--sdk-reference)
9. [Architectural Patterns](#9-architectural-patterns)
10. [Known Limitations (Jaggedness)](#10-known-limitations-jaggedness)
11. [Use Cases & Industry Applications](#11-use-cases--industry-applications)
12. [Integration with AI Agent Ecosystems](#12-integration-with-ai-agent-ecosystems)
13. [Competitive Positioning](#13-competitive-positioning)
14. [Cookbooks & Applied Examples](#14-cookbooks--applied-examples)
15. [Conclusion & Assessment](#15-conclusion--assessment)

---

## 1. Executive Summary

TypeSafe AI, a San Francisco-based company founded in 2024, has introduced **Jev** — the first model in a new category they call **System One models**. Released in limited early access on September 15, 2026, alongside a $40M seed round led by DCVC, Jev represents a fundamentally different approach to AI inference.

**Key thesis:** Jev is not a large language model (LLM). It does not generate text. Instead, it evaluates typed questions against a state (context) and returns structured, typed values with calibrated probability distributions. The model operates at 70–500ms latency, costs $0.042 per million input tokens (output tokens are free), and evaluates all questions in parallel within a single request.

The name "System One" draws from Daniel Kahneman's *Thinking, Fast and Slow* — representing fast, intuitive decisions as opposed to the slow, deliberate reasoning of "System Two" models (like chain-of-thought LLMs).

---

## 2. Company Background

- **Company:** TypeSafe AI
- **Headquarters:** San Francisco, CA
- **Founded:** 2024
- **Notable co-founder:** Diogo Almeida, credited as a co-inventor of RLHF (Reinforcement Learning from Human Feedback), the technique behind InstructGPT and ChatGPT
- **Funding:** $40M seed round led by DCVC (announced September 15, 2026)
- **Stealth period:** ~2 years of development before public launch
- **Training data:** Entirely synthetic (per TechCrunch reporting)
- **Current model:** Jev 1.13.0 (as of September 2026)
- **Waitlist:** Removed September 21, 2026 — open access

---

## 3. The System One Model Category

### Definition

System One models are "a class of AI models built to make fast, structured decisions that software can use directly." They understand natural-language input similarly to LLMs, but their output is fundamentally different — typed decisions and calibrated probabilities rather than generated text.

### Core Properties

| Property | Description |
|----------|-------------|
| **Structured** | Type-safe by construction; outputs conform to JSON schema — no parsing of generated prose |
| **Parallel** | Questions evaluate independently; one result doesn't become hidden context for another |
| **Comparable** | Outputs are sortable — enables thresholds, comparisons, conditional logic |
| **Fast** | ~100ms per query, suitable for real-time request paths |
| **Calibrated** | Communicates uncertainty through calibrated probabilities |
| **Self-consistent** | Designed for stable answers across repeated evaluations |

### What System One Models Do NOT Do

- Do not generate text, write code, or produce reasoning explanations
- Do not stream text, call tools, or edit files
- Do not hold conversations
- Cannot replace the LLM behind coding agents like Claude Code, Cursor, or Copilot

### The Machine Native Intelligence Philosophy

TypeSafe estimates roughly "99% machine-to-machine interactions and 1% human interaction" in large-scale automation. Their approach — which they call **Machine Native Intelligence** — optimizes for structure, reliability, observability, testability, speed, consistency, and low cost rather than conversational fluency.

---

## 4. Jev: Technical Specifications

### Model Identity

| Spec | Value |
|------|-------|
| **Current version** | jev-1.13.0 |
| **Aliases** | `jev-latest` (stable, SDK default), `jev-preview` (latest regardless of status; currently same as jev-latest) |
| **Category** | System One model |
| **Endpoint** | `POST /v1/systemone` |
| **Input modality** | Text only (string, JSON object, array) — no images, audio, or video |
| **Primary language** | English (CJK and others accepted but with lower accuracy) |

### Performance

| Metric | Value |
|--------|-------|
| **Latency** | 70–500ms end-to-end |
| **Speed advantage** | 40–200x faster than frontier LLMs (per TypeSafe claims) |
| **Parallelism** | All questions in a request evaluate concurrently; adding questions barely changes response time |

### Pricing

| Metric | Cost |
|--------|------|
| **Per million input tokens (Mtok)** | $0.042 |
| **Per billion input tokens (Btok)** | $42 |
| **Output tokens** | Free |

### Context Window

| Constraint | Limit |
|------------|-------|
| **Total per request** (state + all questions combined) | 64k tokens |
| **State + longest single question** | 32k tokens |

The dual-budget system means Jev ingests the state once and evaluates every question against it in parallel — the state plus all questions must fit within 64k, while the state plus any single longest question must fit within 32k.

### Rate Limits

| Metric | Limit |
|--------|-------|
| **Tokens per second** | 100,000 |
| **Requests per second** | 40 |

Rate limits are "adjusting dynamically" and "can change without notice." Enterprise customers can negotiate higher limits via sales@typesafe.ai.

### Data Handling

- Jev is **not trained on customer requests or responses**
- Zero Data Retention (ZDR) available for enterprise
- No fine-tuning or LoRA — same weights serve every account
- Customization is entirely through the request (state, instructions, criteria, decomposition)

### Access Points

| Platform | Details |
|----------|---------|
| **Console** | console.typesafe.ai |
| **API** | api.typesafe.ai/v1/systemone |
| **Playground** | console.typesafe.ai/playground |
| **OpenRouter** | base_url: `https://openrouter.ai/api`, model: `~typesafe/jev-latest` |
| **Vercel AI Gateway** | base_url: `https://ai-gateway.vercel.sh/typesafe`, model: `typesafe-ai/jev` |
| **Pydantic AI Gateway** | base_url: `https://gateway-us.pydantic.dev/proxy/typesafe`, model: `jev-latest` |
| **Pydantic AI** | Available as `TypeSafeModel` |

---

## 5. The Three Primitives

TypeSafe defines exactly three question types — called "primitives" — that are the atomic building blocks for all evaluations. They are described as "modular, composable, structured, reliable, and fast."

### 5.1 Choice

**Purpose:** Select one option from a defined, unordered set.

**Returns:** `choice` (selected option), `probabilities` (per-option distribution), `confidence`

**Best for:** Routing tickets, classifying documents, detecting languages, intent classification — any situation where the answer is one of a known finite set.

**Limits:** Maximum 255 options per question.

**Request schema:**

```json
{
  "type": "choice",
  "instructions": "Which team should handle this?",
  "criteria": {
    "billing": "Payment or subscription issues",
    "technical": "Bugs or integration problems",
    "sales": "Pricing or account questions"
  }
}
```

**Response:**

```json
{
  "type": "choice",
  "choice": "technical",
  "confidence": 0.78,
  "probabilities": {
    "technical": 0.85,
    "billing": 0.15,
    "sales": 0.0
  }
}
```

**Key design guidance:**
- Include exhaustive options; add `other` or `none_of_the_above` when coverage may be incomplete
- Use `null` as description when option names are self-explanatory
- For deep taxonomies, chain Choice questions level-by-level (hierarchical classification)
- Criteria values can be strings, objects (`what`/`not_for`/`examples`), arrays, or `null`

### 5.2 Score

**Purpose:** Rate content against ordered, descriptive levels (a spectrum).

**Returns:** `score` (probability-weighted mean, can fall between levels), `legend` (level descriptions), `probabilities` (per-level distribution), `confidence`

**Best for:** Severity assessment, frustration levels, experience depth, quality ratings — anything on an ordered rubric.

**Limits:** Minimum 2 levels, maximum 10 levels. Levels are zero-indexed.

**Request schema:**

```json
{
  "type": "score",
  "instructions": "How frustrated the customer appears",
  "criteria": [
    "Calm, just stating facts",
    "Frustrated but civil",
    "Very angry, strong language"
  ]
}
```

**Response:**

```json
{
  "type": "score",
  "score": 1.43,
  "confidence": 0.35,
  "legend": { "0": "Calm...", "1": "Frustrated...", "2": "Very angry..." },
  "probabilities": { "0": 0.0, "1": 0.57, "2": 0.43 }
}
```

**Score calculation:** `Σ(level_number × probability)` — e.g., `0×0.0 + 1×0.57 + 2×0.43 = 1.43`

**Key design guidance:**
- Describe situations, not degrees ("Broken feature with workaround" > "Moderately severe")
- Numbers-only levels fail — the model needs text to match against
- One dimension per question; multi-dimensional levels cause confusion
- Different distributions can produce the same score — always read probabilities alongside
- Normalize to 0–1 by dividing by `len(criteria) - 1` for cross-dimension comparison

### 5.3 Noul

**Purpose:** Answer a yes/no question, returning the probability that the answer is "yes."

**Returns:** `noul` (float, 0 to 1) — no separate confidence value.

**Best for:** PII detection, refund requests, keyword/concept presence, binary eligibility checks — any binary judgment where the probability itself is the signal.

**Request schema:**

```json
{
  "type": "noul",
  "instructions": "Does this message express urgency?",
  "criteria": {
    "true": "Message conveys time pressure or immediate need",
    "false": "No urgency expressed"
  }
}
```

**Response:**

```json
{
  "type": "noul",
  "noul": 0.95
}
```

**Why no confidence field:** The probability has only two outcomes (yes/no), so the noul value "describes it completely." Near 0.5 = uncertain; near 0 or 1 = confident.

**Critical distinction — probability vs. degree:**
> A Noul value of 0.5 means the model gives yes and no equal probability. It does NOT mean the candidate has a medium skill level.

For measuring degrees, use Score.

**Key design guidance:**
- One condition per Noul; combine multiple conditions in code
- Phrase so high = yes (positive case)
- Statements work: "The customer is requesting a refund" → near 1 means true
- Use the three-way split pattern (yes/uncertain/no) for routing uncertain cases to human review
- `criteria` is optional; the instruction alone is enough for most cases

### Choosing Between Types

| Need | Primitive |
|------|-----------|
| One option from an unordered set | **Choice** |
| A position on a defined spectrum | **Score** |
| A yes/no probability | **Noul** |

### Batching Rules

1. All questions in a single request share the same state
2. Types can be mixed freely (Choice + Score + Noul in one call)
3. Questions run in parallel — "adding questions barely changes the response time"
4. Cost is only the extra tokens for additional questions
5. Questions are independent — one answer is not hidden context for another
6. Benchmark: 13 questions batched into one call was 11.5x cheaper and 9.6x faster than 13 separate calls

---

## 6. Training Methodology: RLCD

### Three Post-Training Paradigms

TypeSafe frames three distinct paths for adapting pretrained models:

| Method | Invented/Pioneered By | Optimizes For | Output |
|--------|----------------------|---------------|--------|
| **RLHF** | Diogo Almeida (TypeSafe co-founder), et al. | Human preference | Natural language responses |
| **RLVR** | Various | Verifiable correctness | Reasoning chains |
| **RLCD** | TypeSafe | Calibrated decisions | Typed values + probabilities |

### RLCD: Reinforcement Learning for Calibrated Decisions

RLCD is TypeSafe's proprietary training method. It defines a fundamentally different output contract:

1. The model does not generate text
2. It returns decisions and probabilities
3. Higher probability corresponds to greater chance the answer is correct

### What Calibration Means

A well-calibrated model's predictions, across many instances, match real-world frequencies:
- Predictions at probability 0.2 should be correct ~20% of the time
- Predictions at probability 0.8 should be correct ~80% of the time
- Predictions at probability 1.0 should be correct ~100% of the time

**Important caveat:** "These rates describe groups of predictions, not a guarantee about any single answer."

### Why Not RLHF for Automation?

TypeSafe identifies specific RLHF failure modes for production automation:

- **Sycophancy and hallucinations:** Preference optimization can reward confident-sounding but wrong answers
- **Mode dropping:** RLHF causes the model to favor a particular style while reducing probability of other outputs
- **Mode collapse:** Extreme version where the model produces the same output type repeatedly
- **Misaligned optimization target:** "Human preference and machine trustworthiness are different optimization targets"

### Training Details

- Jev was trained entirely on synthetic data (per TechCrunch)
- Two years of development in stealth before launch
- No fine-tuning or LoRA adaptation with customer data
- Same weights serve every account
- Model architecture details, parameter counts, and specific training procedures are not publicly disclosed

---

## 7. Confidence & Calibration System

### Core Concept

Confidence measures how concentrated or spread out a probability distribution is. It's a single number from 0 to 1 derived from the `probabilities` property.

- **1** = all probability on one outcome
- **0** = probability spread evenly across all outcomes

### Mathematical Formulas

#### Noul Confidence (computed client-side if needed)

No built-in confidence field. The formula:

$$\text{confidence} = |2p - 1|$$

Yields 0 at p = 0.5 (maximum uncertainty) and 1 at p = 0 or p = 1 (maximum certainty).

#### Choice Confidence

For n options where p_max is the top probability:

$$\text{confidence} = \frac{p_{\max} - \frac{1}{n}}{1 - \frac{1}{n}}$$

Measures how far the top probability sits above an even split. Only the largest probability matters.

```python
def choice_confidence(probabilities: list[float]) -> float:
    n = len(probabilities)
    return (max(probabilities) - 1 / n) / (1 - 1 / n)
```

#### Score Confidence

Because levels are ordered, distance from the peak matters:

$$\text{confidence} = \max\left(0,\ 1 - \frac{\sum_i p_i |i - m|}{\text{MAD}_{\text{unif}}}\right)$$

Where MAD_unif is the mean absolute deviation of a uniform distribution from the midpoint.

Key distinction from Choice: probability on a neighboring level lowers confidence less than the same probability on a distant level.

```python
def score_confidence(probabilities: list[float]) -> float:
    n = len(probabilities)
    m = probabilities.index(max(probabilities))
    spread = sum(p * abs(i - m) for i, p in enumerate(probabilities))
    even_spread = sum(abs(i - (n - 1) / 2) for i in range(n)) / n
    return max(0.0, 1 - spread / even_spread)
```

### Alternative Measures

Two simpler measures from the same probabilities:

1. **Top probability (p_max):** "How likely is the selected option." Meaning is option-count-dependent.
2. **Top-to-second ratio (p_max / p_second):** "How clearly the selected option beats the runner-up."

### Three-Path Routing Pattern

| Confidence Range | Action | Rationale |
|------------------|--------|-----------|
| **High** | Act automatically | Clear model read |
| **Medium** | Proceed with caution | Ask user to confirm, flag for review |
| **Low** | Do not act | Route to human or fallback system |

### Risk-Scaled Thresholds

A core principle: **confidence thresholds are not one number.** Different actions require different thresholds based on stakes:

- Below 0.5: route to human regardless (model genuinely unsure)
- Read-only action (check_balance): accept at moderate confidence (worst case: wrong screen shown)
- Destructive action (approve_transfer): require >0.9 for automatic; moderate triggers confirmation

---

## 8. API & SDK Reference

### HTTP API

**Endpoint:** `POST https://api.typesafe.ai/v1/systemone`

**Authentication:** `Authorization: Bearer <API_KEY>`

**Request body:**

```json
{
  "state": "<string | object | array>",
  "model": "jev-latest",
  "questions": {
    "<user_chosen_id>": {
      "type": "choice | score | noul",
      "instructions": "<string | object | array>",
      "criteria": "<varies by type>"
    }
  }
}
```

**Response body:**

```json
{
  "model": "jev-1.13.0",
  "answers": {
    "<question_id>": {
      "type": "...",
      // type-specific fields
    }
  },
  "usage": {
    "input_tokens": 392,
    "output_tokens": 65
  }
}
```

**Error codes:**

| Status | Meaning |
|--------|---------|
| 401 | Missing/invalid API key |
| 422 | Request body validation failure |
| 429 | Rate limit exceeded |
| 529 | TypeSafe temporarily overloaded |

**Additional endpoint:** `GET /v1/models` — lists all models available to the caller's account.

### Python SDK

**Installation:**
```bash
pip install typesafe-sdk        # basic
pip install typesafe-sdk[http2] # with HTTP/2 support
```

**Exports:** `TypeSafeClient`, `AsyncTypeSafeClient`, `Choice`, `Score`, `Noul`

**Sync usage:**
```python
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

with TypeSafeClient() as client:
    response = client.system_one(
        state={"ticket": "..."},
        questions={
            "dept": Choice(instructions="...", criteria={...}),
            "urgent": Noul(instructions="..."),
            "severity": Score(instructions="...", criteria=[...]),
        },
    )
print(response.answers["dept"].choice)
print(response.answers["urgent"].noul)
print(response.answers["severity"].score)
```

**Async usage:**
```python
from typesafe_sdk import AsyncTypeSafeClient

async with AsyncTypeSafeClient() as client:
    response = await client.system_one(state=..., questions=...)
```

**Response access patterns:**
- `response.answers["key"].choice` / `.noul` / `.score`
- `response.nouls["key"].noul` (filtered accessor)
- `response.choices["key"].choice` (filtered accessor)
- `response.scores["key"].score` (filtered accessor)

**Typed responses:** Subclass `SystemOneResponse` with typed answer fields for attribute-style access.

**Configuration:**

| Env Var | Purpose | Default |
|---------|---------|---------|
| `TYPESAFE_API_KEY` | API key (required) | — |
| `TYPESAFE_BASE_URL` | API root URL | `https://api.typesafe.ai` |
| `TYPESAFE_DEFAULT_MODEL` | Default model | `jev-latest` |
| `TYPESAFE_LOG_LEVEL` | Logger level | unset |

**Retries:** Built-in via `RetryPolicy(max_retries=3, backoff_max=0.2, timeout=1.0)`. Configurable per-client or per-call.

**Error handling:** Catch `TypeSafeAPIError` with `.status` and `.request_id`.

**Forward compatibility:** `extra_body` for sending new API fields; raw dict questions for new types; unknown answer kinds logged and skipped.

### JavaScript/TypeScript SDK

**Installation:** `npm install @typesafe-ai/sdk`

**Requirements:** Node.js >= 20

**Ships with:** ESM, CommonJS, and TypeScript declarations.

```typescript
import { choice, TypeSafeClient } from "@typesafe-ai/sdk";

const client = new TypeSafeClient();
const response = await client.systemOne({
  state: { document: "..." },
  questions: {
    category: choice("What is this about?", { billing: null, technical: null }),
  },
});
console.log(response.answers.category.choice);
```

**Type inference:** Answer types are statically typed based on question definitions — IDE autocompletion and compile-time checking work automatically.

---

## 9. Architectural Patterns

TypeSafe documents four core architectural patterns:

### 9.1 Speculative Fan-Out

**Core idea:** Send all questions your system might need — including speculative ones — in a single call. Let code decide post-hoc which answers are relevant.

**Why it works:** All questions evaluate in parallel with negligible latency impact. Benchmark: batching 13 questions was 11.5x cheaper and 9.6x faster than 13 separate calls.

**Pattern:**
```
Single request with 5+ questions → Single response → Code branches on primary answer → 
Uses relevant speculative answers, ignores the rest
```

**Example:** A support ticket triage sends category, bug_severity, has_reproducible_steps, refund_requested, and frustration all at once. If the category is "feature_request," bug_severity and refund_requested answers are simply never accessed.

### 9.2 Confidence-Gated Routing

**Core idea:** "The answer tells you what; confidence tells you whether to act." Use confidence as a second decision axis alongside the primary answer.

**Three-tier architecture:**

| Confidence | Low-risk action | High-risk action |
|------------|-----------------|------------------|
| Above threshold | Execute | Execute |
| Moderate | Execute | Confirm with user |
| Below floor | Escalate to human | Escalate to human |

**Key principle:** Risk-proportional thresholds — higher-consequence actions demand higher confidence. Thresholds live in application code, adjustable without changing the model.

### 9.3 Composite Scoring

**Core idea:** Break a complex judgment into atomic Score questions per dimension. Normalize each to 0–1. Apply role-specific weight vectors in code.

**Pattern:**
```
Single request → 4 dimension scores → Normalize each (score / max_level) →
Apply weight vector → Weighted sum = composite score → Rank candidates
```

**Key properties:**
- Same raw scores feed different weight vectors for different roles (no redundant API calls)
- Transparent: "visibility into how exactly the final score is being calculated"
- Tunable: adjust weights without retraining
- Separation of concerns: model handles qualitative judgment; code handles aggregation

### 9.4 Intent Routing

**Core idea:** Use TypeSafe as a lightweight, cheap classifier upstream of expensive handlers (specialist LLMs, human agents, deterministic code).

**Pattern:**
```
Incoming message → TypeSafe classifies intent + complexity (1 request) →
Code routes based on intent:
  - order_status → deterministic code (no LLM)
  - product_question → specialist LLM
  - complaint + high complexity → human agent
  - complaint + low complexity → complaint-resolution LLM
  - low confidence on anything → human agent
```

**Three paths to human escalation:**
1. Low intent confidence (model can't classify)
2. High complexity (automated resolution unsafe)
3. Low complexity confidence (unsure how complex)

---

## 10. Known Limitations (Jaggedness)

TypeSafe publishes a remarkably candid "jaggedness" page documenting nine known failure modes of Jev 1.13:

### 10.1 Literal Reading

The model answers the question you wrote, not the one you meant. Interprets scoping words, negations, and implied conditions at face value.

**Fix:** State exact conditions. Put boundary cases in criteria. Split ambiguous questions into two literal ones combined in code.

### 10.2 Math and Numbers

- **Counting:** Does not count reliably. Error grows with size. Recognizes the "shape" rather than tallying.
- **Numeric representations:** Semantic representations > numeric. Hex colors unreliable; English color names work. High-level languages > assembly.
- **Score interpolation:** Weak numerical calibration between levels; thresholds usable, precise interpolation not.

**Fix for counting:** Iterate over items, ask one Noul per candidate, sum in code.

### 10.3 Date and Time Comparison

Reads dates as text, not ordered quantities. Ordering, duration, and window membership unreliable, especially with mixed formats.

**Fix:** Use Choice for extraction (pick month/day/year from options), then assemble and compare in code.

### 10.4 Indirection

Double negatives and complex indirection reduce reliability. Multi-hop reasoning (property of a property) costs accuracy.

**Fix:** Write instructions directly. Reference relevant state by name.

### 10.5 Large Irrelevant State

Accuracy falls as state grows with content unrelated to the decision. Unrelated detail acts as distractor. Jev "suffers from context rot."

**Fix:** Pre-filter with a Noul for relevance. Send only needed context.

### 10.6 Adversarial Content

Does not treat state as hostile by default. Injected instructions, misleading framing, or text arguing for its own classification can steer outputs.

### 10.7 Contradictory Instructions and Criteria

When instructions and criteria conflict, the model gets confused. A Noul where "true maps to no and false maps to yes" performs worse.

### 10.8 Structural Invariants Not Guaranteed

The model is "extremely consistent" for semantically similar inputs but does NOT guarantee structural invariants:

**Noul vs. Choice divergence on identical question:**

| Primitive | Value |
|-----------|-------|
| Noul | noul = 0.22 |
| Choice (yes/no) | yes = 0.01, no = 0.99, confidence = 0.97 |

**Negation asymmetry:**

| Question | Noul |
|----------|------|
| "Is customer asking for refund?" | 0.72 |
| "Is customer asking for something other than refund?" | 0.47 |
| **Sum** | **1.19** (not 1.0) |

P(noul) and 1 - P(not noul) are not complementary. Thresholds tuned on Nouls should not transfer to Choices.

### 10.9 Generation

Not trained to generate text. Forcing generation via chained choices is slow and ineffective. Use regex or a generative model for candidate generation, then let Jev select.

---

## 11. Use Cases & Industry Applications

### Five High-Level Categories

| Category | Key Advantage |
|----------|--------------|
| **AI Automation Software** | Code owns control flow; Jev handles semantic decisions |
| **Real-time Applications** | 150ms latency enables in-loop decisions |
| **AI Map Reduce over Big Data** | 100x cheaper enables corpus-scale processing |
| **Universal Verification** | Verify prompts, extractions, traces, tool calls of other AI |
| **Harness Engineering** | Model routing, semantic retrieval, guardrails, trace classification |

### Ten Decision Shape Categories

| Shape | Description |
|-------|-------------|
| Classification | One known category wins |
| Detection | Probability of one property's presence |
| Scoring | Position on an ordered rubric |
| Routing | Category selects next code path |
| Search | Find items matching NL query |
| Retrieval | Get most relevant context/records |
| Ranking | Order items by semantic relevance/quality |
| Verification | Check artifact for specific failure modes |
| ML Feature Extraction | Generate semantic signals for classical ML |
| Structured Data Extraction | Recover known fields from unstructured input |

### 19 Documented Industry Verticals

1. Search & Retrieval
2. Scientific Discovery
3. Model Routing
4. LLM Guardrails
5. Semantic Code Linting
6. Feature Extraction for Predictive Modeling
7. Recruiting
8. Lead Generation
9. Customer Support
10. Insurance Claims
11. Financial Crime
12. Legal & Compliance
13. E-commerce Marketplaces
14. Moderation & Trust & Safety
15. Advertising
16. Gaming
17. Risk Assessment
18. Demand Forecasting
19. Graphs & Knowledge Graphs

---

## 12. Integration with AI Agent Ecosystems

### The Relationship

Jev is explicitly **not** a replacement for coding agents. It complements them:

- **Coding agents** (Claude Code, Cursor, Codex, Copilot) write text, call tools, edit files
- **Jev** provides fast, cheap, typed decisions that guide what agents do next

### MCP (Model Context Protocol) Integration

The `typesafe-mcp` connector gives AI agents direct access to Jev's typed judgments:

```
Claude Code / Desktop / Codex → MCP evaluate tool → TypeSafe API → 
Typed judgment with probabilities (≈300ms) → Agent acts on structured result
```

Available via AnythingMCP — works in Claude Desktop, ChatGPT, Cursor, Codex, Gemini.

### Agent Skill

TypeSafe publishes a dedicated agent skill providing coding agents full context on the Jev API, primitives, and patterns.

**Installation for Claude Code:**
```bash
claude plugin marketplace add typesafe-ai/skills
claude plugin install typesafe@typesafe-ai
```

**For other agents:**
```bash
npx skills add typesafe-ai/skills --skill typesafe-ai
```

### Community Integration Projects

- **typesafe-mcp:** Thin MCP connector for Claude → Jev
- **fast-jev-compaction:** Session compaction
- **jev-pruner:** Trimming long Bash output
- **jev-guard:** Pre-tool security gate
- **wotai-dev/typesafe-jev-tools:** Claude Code hook + 149-row Jev vs. Haiku comparison

---

## 13. Competitive Positioning

### What Jev Competes With

Jev does not compete with LLMs directly. It competes with:

1. **LLM-as-classifier patterns** — using GPT-4/Claude/etc. with "return JSON" prompts for structured decisions
2. **Traditional ML classifiers** — trained per-task models for classification/scoring
3. **Rules engines** — hard-coded decision logic
4. **Embedding-based similarity** — vector search for routing/classification

### Advantages Over LLM Classifiers

| Dimension | LLM Classifier | Jev |
|-----------|----------------|-----|
| Speed | 1-10s | 70-500ms |
| Cost | ~$1-15/Mtok | $0.042/Mtok |
| Output | JSON parsing required | Type-safe by construction |
| Calibration | Overconfident, uncalibrated | Calibrated probabilities |
| Batching | Sequential questions | Parallel, independent questions |
| Hallucination risk | Can hallucinate categories | Constrained to supplied options |

### Advantages Over Traditional ML

| Dimension | Traditional ML | Jev |
|-----------|---------------|-----|
| Training data needed | Large labeled datasets | Zero (natural-language criteria) |
| Deployment | Model per task | Single model, criteria in request |
| Adaptability | Retrain for changes | Change criteria text |
| Unstructured input | Feature engineering needed | Native text understanding |

### Reviewer Consensus

Per reviewers (eesel.ai, DataCamp, width.ai):
- Real, useful primitive: fast, cheap, type-safe decisions with calibrated confidence
- Clean mental model for composing in code
- Speed and price hold up for what it's designed for
- "Can't hallucinate" claim is oversold (structural invariant issues)
- Benchmark headline is "louder than the (still good) reality underneath"

---

## 14. Cookbooks & Applied Examples

TypeSafe provides 19 end-to-end cookbooks demonstrating real applications:

| Cookbook | What It Demonstrates |
|---------|---------------------|
| **Self-consistency: nouls** | Route uncertain probabilities to human review |
| **Self-consistency: choices** | Compare label agreement with automatic action share |
| **Parallel questions** | 13-question regulatory briefing; 12.2x cheaper, 10.0x faster |
| **Re-ranking** | BM25 shortlists + Jev: top-1 accuracy 5%→18%, top-10 38%→62% |
| **Line-by-line search** | Semantic search over 218 lines of GitHub ToS |
| **Structure recovery** | Reconstruct Markdown from plain text via two-request pipeline |
| **Function calling** | Map NL trading requests to typed function calls |
| **Skill suggestion** | Pick 1 skill from 182 in the Hermes catalog (two-request) |
| **Entity alignment** | 450 candidate pairs from beer catalogues |
| **Classifying RAG passages** | Score/filter passages before sending to answering model |
| **Double-checking citations** | Catch wrong/hallucinated citations against source |
| **Guardrails for LLMs** | Screen every message; threshold hazard probabilities |
| **SDE cascade** | 2-stage structured data extraction (mini → verify → reasoning) |
| **Date extraction** | Named parts → code resolution with confidence-based review |
| **Pre-parsed value extraction** | Regex candidates + Jev selection |
| **Hierarchical classification** | Deep taxonomy beam search (patent, retail, biomedical, source-code) |
| **Autoresearch feature discovery** | Autoresearch loop proposing questions → CatBoost improvement |
| **Classification using confidence** | SEC reports into 75 industry groups with confidence-based fallback |

---

## 15. Conclusion & Assessment

### What Jev Is

Jev represents a genuine new category of AI model. It is not an incremental improvement on LLMs but a fundamentally different tool optimized for a different job: fast, structured, calibrated decisions that software consumes directly.

### Strengths

1. **Clean abstraction:** Three primitives (Choice, Score, Noul) compose into complex behavior through ordinary code
2. **Speed:** 40-200x faster than LLMs for classification/scoring tasks
3. **Cost:** $0.042/Mtok is transformatively cheap for high-volume decision-making
4. **Calibration:** Probabilities that actually mean something, enabling principled confidence-gated routing
5. **Parallel evaluation:** Ask many questions in one call with negligible latency impact
6. **No parsing:** Type-safe by construction — no JSON extraction, no hallucinated fields
7. **Composability:** Code owns control flow; model handles narrow judgments
8. **Transparency:** Full probability distributions enable custom routing logic

### Weaknesses & Risks

1. **Text only:** No image, audio, or video input — limits applicability
2. **English-centric:** Lower accuracy for non-English content
3. **Context rot:** Accuracy degrades with large irrelevant state
4. **Structural invariants not guaranteed:** Noul/Choice divergence on equivalent questions
5. **No counting/math:** Cannot reliably count or compare numeric values
6. **Adversarial vulnerability:** Does not treat state as hostile
7. **Single vendor:** No competing System One models yet
8. **Opaque architecture:** No published parameter counts, training details, or architecture specs

### Strategic Significance

Jev's design philosophy — "code owns the control flow, model handles narrow semantic decisions" — represents a counter-narrative to the dominant agentic AI trend where models increasingly control execution. If the thesis holds that 99% of AI automation is machine-to-machine, then the tooling gap Jev fills (fast, cheap, structured decisions) is significant.

The $40M seed and the pedigree of having an RLHF co-inventor leading a post-RLHF training paradigm (RLCD) lend credibility. The self-published jaggedness page — with specific, quantified failure modes — signals unusual engineering candor.

### Open Questions

1. How does accuracy scale as the model family evolves? (No benchmarks published)
2. Will multi-modal input (images, audio) arrive, and how?
3. How does RLCD compare to RLHF/RLVR on overlapping tasks at scale?
4. Will competitors enter the System One category?
5. How does calibration hold across domains, languages, and edge cases not covered by synthetic training data?

---

## Appendix: Documentation Map

TypeSafe's full documentation spans **111 pages** as indexed at `docs.typesafe.ai/llms.txt`, covering:

- 3 introduction pages
- 3 concept pages
- 5 primitive reference pages
- 1 confidence page
- 2 building guides
- 4 pattern pages
- 19 cookbook pages
- 2 demo pages
- 2 model/API reference pages
- 2 agent/legal pages
- 1 jaggedness page
- 12 Python SDK pages
- 47 JavaScript SDK pages (including full TypeDoc-generated API reference)

---

*Research compiled from primary source: docs.typesafe.ai (accessed October 2026)*
