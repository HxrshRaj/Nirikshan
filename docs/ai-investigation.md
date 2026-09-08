# AI Investigation

## Flow

```mermaid
sequenceDiagram
  participant Eng as Engineer / worker
  participant Orc as Investigator (Python playbook)
  participant Tool as Evidence tools
  participant DB as PostgreSQL
  participant LLM as Provider (mock | openai | groq)

  Eng->>Orc: investigate(incident)
  Orc->>DB: create AgentRun (RUNNING), transition DETECTED->INVESTIGATING
  loop SRE playbook
    Orc->>Tool: query_metrics / search_logs / get_recent_deployments / get_dependencies / get_error_traces / get_alert_history / get_related_incidents
    Tool->>DB: scoped, typed read
    Tool-->>Orc: curated result (rows, summary) + AgentToolCall row
  end
  Orc->>Orc: assemble evidence bundle (provenance-tagged ids)
  Orc->>LLM: analyze(bundle, prompt@version)
  LLM-->>Orc: {root_cause, confidence, hypotheses[], factors, actions}
  Orc->>Orc: validate + ground (drop uncited ids, clamp confidence)
  Orc->>DB: persist evidence rows + ranked hypotheses + RCA; AgentRun COMPLETED; LLMCall ledger
  Orc-->>Eng: INVESTIGATION_COMPLETED (or FAILED, retryable)
```

## Why tools instead of giving the model the database

1. **Auditability** — every access is a named call with typed arguments,
   recorded as an `AgentToolCall` (sequence, args, ok, row count, summary,
   duration). The UI shows the whole trail.
2. **Least privilege** — the model never sees raw rows, DSNs, secrets, or data
   for services outside the incident. It sees a bounded, curated bundle.
3. **Determinism & testability** — the same tools feed the evaluation harness
   and integration tests; investigations are reproducible on the deterministic
   scenarios.
4. **Rate-limiting & cost control** — each tool is individually limitable; the
   bundle size is bounded regardless of how much telemetry exists.

The control loop itself is explicit Python (a fixed SRE playbook). The provider
is used only for the **synthesis** step. A model-driven tool-use loop with
per-tool budgets is listed as future work.

## Grounding & anti-hallucination

`_collect_evidence_ids(bundle)` enumerates the valid ids
(`metric:<name>`, `anomaly:<name>`, `deploy:<REF>`, `prior:<INC>`,
`dep:unhealthy:<svc>`, `logs:*`). For a remote provider, `_validate_analysis`:

- drops any `supporting_evidence_id` not in that set (recorded as a warning),
- caps a hypothesis's confidence at 0.5 if it has **no** grounded evidence,
- clamps all confidences to `[0, 1]`,
- rejects the run (`ProviderUnavailable`) if nothing usable comes back.

The mock reasoner is grounded by construction: it only cites ids for evidence
the orchestrator actually collected, and every mock output is labelled
**"Demo / Mock Provider"**.

## The mock / demo reasoner

`ai/mock_reasoner.py` is **not** a language model — it is a deterministic
rule-based SRE analyst over the same evidence bundle. It recognises:
`database_saturation`, `deployment_regression`, `upstream_dependency_failure`,
`traffic_overload`, `resource_saturation`, and `inconclusive` (low confidence
when no single cause reaches the evidence threshold). It produces competing
hypotheses at calibrated confidences so the ranked-hypothesis view is
meaningful. This exists so the platform is fully demonstrable and CI-testable
with zero external credentials — never as a substitute for real analysis.

## Provider abstraction

`LLMProvider.analyze(bundle, prompt)` and `.plan_remediation(context, prompt)`.
`get_llm_provider()` returns `MockProvider` unless `NIRIKSHAN_LLM_PROVIDER` is
`openai`/`groq` **and** `NIRIKSHAN_LLM_API_KEY` is set; otherwise it transparently
falls back to mock. Remote calls use the OpenAI-compatible
`/chat/completions` JSON mode and are strictly parsed + validated.
`EmbeddingProvider` is `LocalHashEmbeddingProvider` (deterministic, offline) by
default, `OpenAIEmbeddingProvider` when configured.

## Prompt versioning

`ai/prompts.py` holds `incident-investigator@v1` and `remediation-agent@v1` with
sha256 checksums, synced into `prompt_versions` on boot. Every `AgentRun`
records the prompt name + version it used.
