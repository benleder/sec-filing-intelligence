# Agent / GenAI Developer — Take-Home Assignment: SEC Filing Intelligence (v2)

**Agent Developer's Take-Home Assignment**

*SEC Filing Intelligence Scenario*

> Tools:
> Use any tools you have access to, including AI coding assistants / “vibe coding” workflows.
> Submission:
> Bring to Interview 2.

# Background

A Fortune 500 leadership team is trying to make faster decisions using public-company financial data from SEC filings.

The data already exists in EDGAR. The problem is that extracting answers is still painful.

Questions like:

- “What was Tesla’s net income growth between 2025 and 2026?”

- “How did Q1 revenue change year-over-year?”

- “Which metrics deteriorated the most last quarter?”

- “What did management say about margin pressure?”

still require analysts to manually open filings, navigate tables, interpret XBRL tags, reconcile periods, and validate calculations.

The company previously experimented with an AI-powered financial assistant. It failed for predictable reasons:

- It hallucinated values not present in filings

- It mixed annual and quarterly numbers

- It confused GAAP vs. non-GAAP metrics

- It provided answers without traceability

- Users could not verify where numbers came from

Executives stopped trusting it.

There is no restriction against using AI internally. But skepticism is high. The bar is not simply “can it answer questions.” The bar is:

> ***“Can we trust the answer enough to make decisions from it?”***

You are coming in as an Agent / GenAI Developer / Applied AI Engineer. The client wants to understand whether modern agentic workflows and LLM systems can materially improve how humans interact with SEC filings.

They have asked you to build a lightweight prototype that demonstrates the direction.

### An important wrinkle: where the data actually comes from

The team has already invested in a historical archive: tens of thousands of filings purchased in bulk as PDF documents directly from SEC, rather than pulled live through the EDGAR API. This decision was driven by a practical constraint — EDGAR rate-limits API requests, which makes querying the live API at the volume this team needs impractical for production use.

This is not a minor detail. It changes the engineering problem. **Your system should treat PDF filings as the primary data source**, not the clean, pre-tagged XBRL JSON that the EDGAR API would otherwise hand you for free. You may still use the live EDGAR API sparingly — for example, to identify which filings exist, or for a handful of validation lookups — but assume it is a constrained, low-volume resource, not your primary pipeline.

Why this matters for what we're evaluating: it is easy to build a convincing demo on top of structured, pre-labeled data and never confront the actual hard problem. The hard problem — the one that burned trust at this company before — lives in messy, inconsistently formatted source documents. We want to see how you think about that problem, not how well you can call a clean API.

# Data Environment

This section describes the data conditions you should assume. It is meant to shape your design decisions, not to dictate a specific architecture.

- **Primary corpus:** a local archive of historical 10-K and 10-Q filings in PDF form, tens of thousands of documents spanning multiple companies and years.

- **You do not need to acquire or process the full archive.** A handful of representative filings — e.g., 3–5 filings for 1–2 companies — is sufficient to demonstrate your approach. Be explicit about what would need to change to make your approach hold up at the full tens-of-thousands-of-filings scale (storage, parsing throughput, indexing strategy, cost).

- **PDF, not XBRL, is your default reality.** Tables in these documents may have inconsistent layouts, multi-column structures, footnotes, restated figures, and GAAP and non-GAAP metrics presented side by side, sometimes in the same table.

- **Treat the live EDGAR API as a constrained resource,** not a primary data path — assume a low daily call budget. Decisions about what you fetch live versus what you rely on from the local archive are part of what we're evaluating.

*A few questions worth sitting with before you start building (you are not required to answer these explicitly anywhere, but strong submissions tend to show evidence that the candidate thought about them):*

- If you can no longer rely on EDGAR's structured XBRL tags to tell you exactly what a number means, how do you figure that out from the PDF itself?

- Does it make more sense to parse and structure the entire corpus once, up front, or to retrieve and interpret raw PDF content live, per question?

- What's actually the right tool for finding a specific number in a financial table — is it the same tool you'd use to find a relevant paragraph of risk-factor prose?

# Your Task

Using a sample drawn from the kind of SEC filings described above, design and build an artifact that allows a user to ask natural-language questions about a company's financials and receive a grounded answer.

Example starting point: *Tesla EDGAR entity landing page* (use this to source a small number of real PDF filings to work with).

Your system does not need to be production-grade or fully accurate across all edge cases.

We are intentionally more interested in:

- your reasoning,

- system design choices,

- agentic workflow decisions,

- tradeoffs,

- trust mechanisms,

- and how you would evolve the system over time.

You may use:

- LLM APIs

- agent frameworks

- RAG pipelines

- browser automation

- XBRL parsers (for validation/spot-checks only — see Data Environment above)

- embeddings / vector DBs

- structured extraction

- coding agents

- “vibe coding” workflows

- or entirely different approaches

The implementation format is flexible. The artifact can be a chat UI, CLI, notebook, agent demo, architecture diagram, lightweight web app, or something else entirely. Use whatever format best communicates your idea.

# Functional Expectations

At minimum, your system should attempt to:

## 1. Answer natural-language financial questions

Examples:

- “What is Tesla’s profit growth from 2025 to 2026?”

- “What was the Q1 revenue change year-over-year?”

- “How did operating margin change?”

- “What are the biggest balance sheet changes?”

- “What did management cite as risks this quarter?”

## 2. Show traceability

Answers should not feel like generic chatbot output. We want to see some notion of:

- filing source,

- reporting period,

- table/section references,

- extracted values,

- calculation steps,

- citations,

- or intermediate reasoning artifacts.

The goal is to help a skeptical finance user verify the answer.

## 3. Handle ambiguity honestly

Financial filings are messy. Your system should acknowledge situations like:

- missing data,

- inconsistent labels,

- multiple possible interpretations,

- quarterly vs. annual confusion,

- unaudited statements,

- amended filings,

- non-GAAP metrics,

- or confidence limitations.

A correct “I'm not fully certain because…” is often better than a polished hallucination.

## 4. Demonstrate an agentic or workflow-oriented approach

We are specifically interested in how you think about orchestration. For example:

- retrieval → extraction → validation → reasoning

- planning agents

- browser/navigation agents

- tool use

- structured intermediate representations

- verification passes

- reconciliation logic

- fallback mechanisms

This does not need to be sophisticated, but it should be intentional.

## 5. Justify your retrieval and extraction approach for numeric tables

This is the part of the system that determines whether the rest of it can be trusted, so we're calling it out as its own expectation rather than leaving it implicit. Be explicit — in your walkthrough or write-up — about how your system actually finds and pulls a specific number out of a filing, and why you built it that way. We're interested in things like:

- **What retrieval mechanism you used** — embeddings/semantic search, layout-aware structured parsing, regex or rule-based extraction, LLM-driven extraction, or some combination — and why that choice fits (or doesn't fit) the structure of a financial table.

- **What you believe embeddings are actually good and bad at.** Embedding models are trained to place semantically or topically similar text close together in vector space — not to encode numerical magnitude, table position, or fine label distinctions. Two line items like “Net income” and “Net income attributable to common stockholders” will likely embed as nearly identical vectors despite referring to different dollar figures a few rows apart. Does your system have any way of noticing or guarding against that kind of near-miss?

- **Where arithmetic happens.** Once you've extracted two raw numbers, is a growth rate or margin computed by deterministic code, or is the LLM asked to compute it directly? What would you expect to go wrong with the latter, and at what scale of numbers does it tend to go wrong?

- **How you know your numbers are actually correct.** With a live XBRL API, checking correctness is close to free — the structured tag tells you what the number means. With PDFs, you have to build your own way of knowing whether an extracted value is right. Even something small and informal — a handful of hand-verified question/answer pairs you checked against the source filing yourself — counts as a real benchmark and is worth more than an unverified demo.

# Suggested Scope

You do not need to solve the entire SEC ecosystem. Reasonable scope reductions are encouraged. For example, you may choose to support only:

- one company,

- a few filing types (10-K / 10-Q),

- a subset of metrics,

- recent filings only,

- a small set of PDFs you've manually downloaded rather than the full purchased archive,

- or structured numeric questions only.

Strong candidates usually make thoughtful cuts rather than attempting everything.

# Example Questions to Test Against

At minimum, your artifact should attempt to answer questions like:

- “What is Tesla’s net income growth between 2025 and 2026?”

- “What was Tesla’s Q1 revenue change year-over-year?”

- “What was Apple’s total revenue in 2025?”

- “What was Microsoft’s net income in the latest annual filing?”

- “What was Amazon’s AWS revenue last quarter?”

- “What was NVIDIA’s operating income for Q1 2026?”

- “How much cash and cash equivalents did Google report?”

- “What was Meta’s diluted EPS in the latest filing?”

- “What is Apple’s net income growth between 2025 and 2026?”

- “What was Microsoft’s Q1 revenue change year-over-year?”

- “How did Amazon’s operating cash flow change?”

- “What were Meta’s biggest expense increases?”

- “How much did Netflix’s SG&A grow as a percentage of revenue?”

- “Calculate NVIDIA’s gross margin for the last two years.”

You are encouraged to add additional examples that highlight your system's strengths.

# Deliverables

For your next interview, bring:

## 1. A tangible artifact

Something concrete that demonstrates the concept. Examples:

- prototype application,

- notebook,

- architecture diagram,

- demo workflow,

- lightweight UI,

- CLI,

- or presentation.

Rough is fine. Something tangible is not optional.

## 2. A 5–10 minute walkthrough

Be prepared to explain:

- what you built,

- architectural decisions,

- where AI/agents were used,

- where they were intentionally not used,

- what shortcuts you took,

- and what you would improve with another day or week.

## 3. A short written or verbal discussion

### Trust & hallucination

- The previous system lost executive trust because it hallucinated financial information. How does your approach reduce that risk?

- Where can it still fail?

- What would you do next to improve reliability?

- If you used embeddings for any part of retrieval, what do you believe they are actually good and bad at — and how did that belief shape your design?

- How did you benchmark your system's numeric accuracy? What does “correct” mean in your evaluation — exact match, a tolerance band, right line item but wrong period, something else?

- Where in your pipeline does the LLM perform arithmetic, versus where does deterministic code perform it — and why did you split it that way?

### Agentic workflow design

- Why did you choose your workflow structure?

- What role should LLMs play vs. deterministic logic?

- Where should validation happen?

- Given that your source data is PDF rather than structured XBRL, did that change where you placed the LLM in the pipeline? Why or why not?

### Product thinking

- What type of user is this best suited for today?

- What is still missing before real enterprise deployment?

- If you had to process the full tens-of-thousands-of-filings archive instead of a handful of sample PDFs, what would break first?

# What We Are Evaluating

This is not a LeetCode exercise. We are not grading primarily on polish, frameworks, or UI quality.

We are evaluating:

### Applied reasoning

Can you design a practical system around an ambiguous real-world problem?

### Engineering judgment

Did you make sensible tradeoffs under time constraints?

### Agentic thinking

Can you structure workflows that combine tools, retrieval, reasoning, and validation coherently?

### Trust & traceability

Do you understand why enterprise users distrust AI-generated financial answers?

### Communication

Can you clearly explain what your system does, what it does not do, and why?

### Product intuition

Did you think about the actual end-user experience?

### AI leverage

AI-assisted implementation is expected and encouraged. How you use AI tooling is part of what we are evaluating.

### Fundamentals, not buzzwords

This is the one we want to be explicit about, because it changes how you should prepare. We are specifically listening for whether you understand *why* your design choices work, not whether you can name the right tools. A candidate who says “I used RAG with embeddings” tells us very little. A candidate who can explain what an embedding model is actually optimized to do, why that objective makes it a poor fit for distinguishing two similarly-worded line items with different dollar values, and what they did instead or in addition — tells us a great deal, even if their demo only handles one company and three filings.

## A note on how this is graded

**There is no fixed answer key for this assignment, and you will not be ranked on whether your numbers happen to match a reference solution.** Financial filings are genuinely messy, and reasonable engineers will make different, defensible choices about scope, architecture, and tooling. What we're ranking is the depth of your understanding of the fundamentals underneath those choices — things like:

- what an embedding actually represents, and what its failure modes are on numeric, tabular content versus narrative prose;

- why retrieval quality and answer correctness are not the same thing, and how you'd notice if they diverged;

- what you can and can't expect an LLM to do reliably (e.g., arithmetic, exact value lookup, consistent period alignment) versus what should be handled by deterministic code;

- how you'd actually benchmark a system like this — what a meaningful evaluation set looks like, and what “correct” should mean;

- and whether you can honestly describe where your own system is weak, rather than only where it's strong.

A smaller, rougher system built by someone who can speak clearly and honestly to these fundamentals will outperform a polished, full-featured demo built by someone who can't explain why it works. Build something real, and come ready to talk about it candidly.
