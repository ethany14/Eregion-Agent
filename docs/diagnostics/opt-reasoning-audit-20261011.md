# Stage 0–1 reasoning audit (2026-10-11)

Scope: source audit against parent `63f77aa`; no `.env` inspection and no paid calls.
“Today” below means the pre-change code's actual request assembly, not an assumption
about private deployed environment values. MAIN = `LLM_MODEL_ID`; FAST =
`LLM_FAST_MODEL_ID` falling back to MAIN; EXTRACT = `LLM_EXTRACTION_MODEL_ID`
falling back to MAIN. “Provider default” means the parameter is absent, not `none`.

| Purpose / new suffix | Construction and call sites | Model setting | Reasoning sent before this change | Output | Quality gate |
|---|---|---|---|---|---|
| career router / `AGENT` | `task_loop.TaskModel` → `create_model()`; `TaskHost.invoke` | MAIN | **Provider default**, despite ledger purpose `agent` | Tool calls / assistant text | B6 replay, `test_task_loop`, request-volume / token-usage tests |
| application router / `AGENT` | `auto_apply.agent` → `shared_model(purpose='agent')` | MAIN | `LLM_AGENT_REASONING`, otherwise absent | Tool calls / text | auto-apply shared-kernel, action/approval and recovery tests |
| fast chat / `FAST` | `auto_apply.agent`; `career.harness` pasted-job check → `shared_model('fast')` | FAST | `LLM_AGENT_REASONING`, otherwise absent | Tool calls; `PastedJobText` | auto-apply fast-options / job-import tests |
| extraction / `EXTRACTION` | `custom_agent.handlers.SharedModelAnalyzer` → `shared_model('extraction')`; `job_extraction.extract_job` | EXTRACT | `LLM_EXTRACTION_REASONING`, otherwise absent | `ResumeExtraction`, `ReferencedJobExtraction` → public analyses | extraction, resume-source, frozen-catalogue tests; A3 before lowering |
| scoring / `SCORING` | same analyzer's `SkillAssessment` branch; compact/batch main fallback | EXTRACT | **Also `LLM_EXTRACTION_REASONING`**, because the constructed model is extraction-routed | `CompactSkillAssessment` → `SkillAssessment` | partial-support / remaining-analysis tests; A1 spread ≤5.6; A3 labels required for lowering |
| pack writer / `PACK_WRITER` | `application_pack.workflow.SharedPackModel` → `shared_model()`; analyzer resume selection/write/revise → `shared_model()` | MAIN | Provider default | `CoverLetter`, `ApplicationAnswer`, `ResumeSelection`, `TailoredResume` | E5 pack/material/cover-style gates plus human style review |
| claim verifier / `CLAIM_VERIFIER` | `semantics.SemanticDecisions._invoke` → `create_model()`; analyzer verifier → `shared_model()` | MAIN (or injected model) | Provider default; injected models retain their own baseline | `ClaimDecisions`, `FactualVerificationResult` / `VerificationResult` | all-claims grounding, ownership, forbidden strengthening, pack tests |
| memory relevance / `MEMORY_RELEVANCE` | `semantics._invoke` → `create_model()` | MAIN | Provider default | `RelevantMemories` | memory isolation / semantic-decision tests |
| question category / `QUESTION_CATEGORY` | `semantics._invoke` → `create_model()` | MAIN | Provider default | `QuestionCategory` | interviewer / semantic fallback tests |
| pasted job / `JOB_SCREENING` | `semantics._invoke`; injected fast model in `career.harness` | MAIN or FAST | Absent for default model; agent reasoning for injected fast model | `PastedJobText` | pasted job recognition and employer/source identity gates |
| mock question / `INTERVIEW_QUESTION` | `mock_interview.model.interview_model(None)` → `create_model('agent')` | MAIN | `LLM_INTERVIEW_REASONING`, default `low` | `MockInterviewQuestion` | C16, mock-interview grounding / plan / protected-attribute tests |
| mock feedback / `INTERVIEW_FEEDBACK` | `interview_model(evaluation_purpose)`, default purpose `fast`, optional `agent` | FAST or MAIN | `LLM_INTERVIEW_REASONING`, default `low` | `MockAnswerEvaluation` | C16 grounding, exact quotes, FIFO / async / failure-lock tests |
| application interview question / `INTERVIEW_QUESTION` schema spelling is `InterviewQuestion` | `interviewer.model.SharedInterviewModel.question` → `create_model()` | MAIN | **Provider default**, not mock-interview `low` | `InterviewQuestion` | `test_interviewer.py` |
| application interview answer / `INTERVIEW_ANSWER_ASSESSMENT` | `SharedInterviewModel.classify` → `create_model()` | MAIN | Provider default | `InterviewAnswerAssessment` | `test_interviewer.py`, confirmation/evidence ownership |
| resume profile / `RESUME_PROFILE` | `auto_apply.resume_profile` chat/PDF extraction → `create_model()` (now explicitly labelled) | MAIN | Provider default | `ResumeFacts` (tool schema or structured output) | profile extraction, education/date/quote tests |
| skill evaluation / `SKILL_EVALUATION` | `skills.evolution_evaluation.ConfiguredEvaluationModel` → `create_model()` (now labelled) | MAIN | Provider default | text → local `ModelObservation` | `test_skill_evolution.py`, isolated holdout cases |
| API / `API` | `api.session_dependencies` → `create_model()` (now labelled), `LangChainToolModelAdapter` | MAIN | Provider default | tool calls / text | session, tool-loop/model-adapter and policy tests |
| unspecified / `NONE` | public `create_model` / `shared_model` default and injected consumers | MAIN | Provider default | caller-defined | default-wire parameterized test |
| `BROWSE`, `APPLICATION` | browser-manager/application-browser **context labels**, not independent model constructors | inherited model | no extra reasoning setting from those labels | browser/tool contract | browser/auto-apply tests; no new model route invented |

`InterviewQuestion` normalizes to `INTERVIEW_QUESTION`; this intentionally shares the
new override with mock questions, while each retains its distinct old default.
Unknown structured schemas normalize CamelCase to upper snake (for example `Tiny`
→ `LLM_REASONING_TINY`). The schema alias table in `job_agent/reasoning.py` is the
authoritative mapping for the grouped purposes above. A shared extraction client
can therefore use a separate scoring override without changing its model ID.

Independent TypeSafe paths (none sent before this change):

| Purpose suffix(es) | Call sites | Model setting | Output / gate |
|---|---|---|---|
| `JOB_SCREENING` | `career.screening` → `FastDecisions.evaluate` | `TYPESAFE_DEFAULT_MODEL` (`jev-latest` default) | choice/probability; screening and B6 |
| `SKILL_EVIDENCE`, `SKILL_EVIDENCE_VERIFY` | `job_agent.fast_match` → FastDecisions | same | choice/probability; partial-support / main fallback gates; A1/A3 |
| `QUESTION_CATEGORY`, `MEMORY_RELEVANCE` | `fast_semantics` → FastDecisions | same | choice/probability; semantic confidence and memory isolation |
| `FORM_OPTIONS` | `auto_apply.runner` → FastDecisions | same | choice/probability; fast-options confidence/approval boundaries |
| `EXTRACT_REQUIREMENTS`, `REFINE_EXTRACTION_YES_NO` | `jev_fit.core` → `Client` / `Broker` | pinned `TYPESAFE_FIT_MODEL`, fallback `TYPESAFE_DEFAULT_MODEL` then `jev-1.13.0` | noul probabilities; extraction/catalogue completeness |
| `CONDITION_CATEGORY_YES_NO`, `SUPPORT_YES_NO`, `FOCUSED_YES_NO`, `CLARIFY_FULL_SUPPORT_YES_NO`, `VERIFY_CITATIONS_YES_NO` | same | same | noul probabilities; production Jev, partial support, citation grounding; A1/A3 |
| unknown-fit resolver / `JEV_FIT_RESOLVER` | `jev_fit.service` → `shared_model('extraction')` | EXTRACT | extraction legacy setting | `UnknownResolution`; resolver identity / cache tests |

TypeSafe support for the new wire parameter is **not assumed to be verified**.
Only explicit new overrides send `reasoning_effort`; an HTTP 400/422 that identifies
reasoning as unsupported gets one parameter-free retry. No paid compatibility test
was run. Leaving all these overrides unset preserves the existing JSON body.

Mechanics:

- Nonblank `LLM_REASONING_<PURPOSE>` wins over the construction path's legacy value.
  Accepted values remain `none`, `minimal`, `low`, `medium`, `high`. Empty values
  mean unset. `none` explicitly sends a value; it is not parameter omission.
- Mock interview preserves its legacy `low`, `default`/`off`, model routing and
  normalization. New question/feedback overrides apply at the structured boundary.
- `JOB_AGENT_REASONING_ESCALATION=1` enables one validation retry for generic
  structured calls, and upgrades the existing batch retry, mock-feedback grounding
  repair, career malformed-output repair and first grounding-driven pack revision.
  `low→medium`, `medium→high`; high/none/minimal/absent stay unchanged. The setting
  is request-local and does not mutate shared clients. Batch/controller retries own
  schema retries so the nested generic helper does not add another retry.
- Provider rejection fallback is bounded separately from validation and never
  retries a tool effect. Escalation and effective level are saved on each concrete
  attempt. Tool action rows are explicitly excluded from provider token totals.
- Shared model/analysis signatures include all new overrides, the legacy interview
  setting and escalation switch. Existing extraction signatures are composed with
  this model fingerprint by `SharedModelAnalyzer.cache_namespace`; they do not
  constitute a model-result cache on their own. Jev signatures and fast decision
  payload keys/namespaces also partition reasoning and escalation policy.
  Results after an actual level upgrade or parameter-free fallback bypass writes
  to the original level's cache key, including durable analysis and resolver caches.

Surprises: career router is not covered by the legacy agent variable; scoring uses
the extraction route; the two interview systems have different defaults; and
schema names/ledger purposes are not always construction purposes. The overrides
therefore resolve at invocation as well as at construction.

Proposed **later paid comparison** (not activated here): career/application router
`low` with B6 and action-policy gates; claim verifier `low` with all-claims/E5 gates;
mock questions/feedback `low` with C16; pack writer `medium` with E5 plus human style
review; simple category/memory/form decisions `low` only after provider compatibility
and existing confidence gates. Keep extraction, scoring and Jev fit unset/current
until A1 and A3 permit a comparison. No proposed value changes a default in this patch.

Complete starting-value matrix for that later comparison:

| Override suffix / route | Proposed starting value | Required quality gate |
|---|---|---|
| `AGENT` | low | B6 unchanged acceptance; application action/approval policies |
| `FAST` | low | auto-apply options and pasted-job classification |
| `PACK_WRITER` | medium | E5 all checks plus human style review |
| `CLAIM_VERIFIER` | low | full claim coverage, ownership and grounding; E5 |
| `INTERVIEW_QUESTION` | low | C16 mock questions **and** application-interviewer tests |
| `INTERVIEW_FEEDBACK` | low (retain mock default) | C16 feedback, quotations, FIFO and async failure handling |
| `INTERVIEW_ANSWER_ASSESSMENT` | low | application-interviewer classification and evidence confirmation |
| `RESUME_PROFILE` | low | exact quotes, school separation, dates, location and consent guards |
| `API` | low | session/tool-loop contract, permissions and structured output |
| `JOB_SCREENING`, `QUESTION_CATEGORY`, `MEMORY_RELEVANCE`, `FORM_OPTIONS` | low, after compatibility check on each transport | screening/B6, semantic confidence, memory isolation, protected-field/options tests respectively |
| `EXTRACTION`, `SCORING`, `SKILL_EVIDENCE`, `SKILL_EVIDENCE_VERIFY` | retain current effective setting | extraction/partial-support fixtures; A1 ≤5.6 and A3 labels before reducing |
| all seven Jev fit purposes above; `UnknownResolution` resolver | retain current effective setting | pinned-model Jev fixtures, frozen catalogue, citation ownership; A1/A3 |
| `SKILL_EVALUATION` | retain provider default | paired positive/negative/boundary/adversarial/tool-policy/holdout evaluation |
| `NONE`, other caller-defined schemas | retain current setting | caller-specific gate must be identified first |
| browser `browse` / `application` labels | inherit existing model route | these are not independent model constructors; gate through B6 / auto-apply |

The main scoring row refers to `SharedModelAnalyzer`'s extraction-routed model.
A direct `create_model(purpose='scoring')` previously sent no reasoning; the distinction
between semantic purpose and model-construction purpose is intentional in this audit.
Semantic purposes retain a separate legacy fallback: a new `EXTRACTION` override
cannot silently lower `SCORING` or `JEV_FIT_RESOLVER` on the same shared client.
