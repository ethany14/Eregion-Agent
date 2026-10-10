"""Framework-independent handlers for the Job Agent computation steps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from custom_agent.state import AgentState, Step
from custom_agent.steps import StepOutcome
from agent_runtime.multi_agent.model_usage import invoke_model
from job_agent.domain import (
    normalize_job_analysis,
    normalize_resume_analysis,
    normalize_skill_match,
    normalize_tailored_resume_claim_ids,
    normalize_text,
    validate_resume_source_metadata,
)
from job_agent.quality import (
    clean_tailored_resume,
    ensure_foundational_resume_sections,
    normalize_generated_resume_metadata,
    quality_result,
    validate_resume_structure,
)
from job_agent.model import DEFAULT_ENV_PATH, create_model, invoke_structured
from job_agent.prompts import (
    JOB_PROMPT,
    MATCH_PROMPT,
    RESUME_PROMPT,
    REVISE_RESUME_PROMPT,
    VERIFY_RESUME_PROMPT,
    WRITE_RESUME_PROMPT,
)
from job_agent.schemas import (
    JobAnalysis,
    ResumeAnalysis,
    ResumeEvidence,
    SkillAssessment,
    TailoredResume,
    UnsupportedClaim,
    VerificationResult,
    FactualVerificationResult,
)


class Analyzer(Protocol):
    def __call__(self, schema: type[BaseModel], system_message: str, human_message: str) -> BaseModel: ...


class SharedModelAnalyzer:
    def __init__(self, env_path: Path = DEFAULT_ENV_PATH) -> None:
        self._env_path = env_path

    def cache_namespace(self):
        from job_agent.model import model_settings_fingerprint
        from job_agent.job_extraction import extraction_signature
        from job_agent.resume_extraction import extraction_signature as resume_signature
        return model_settings_fingerprint(env_path=self._env_path) + ':' + extraction_signature() + ':' + resume_signature()

    def write_resume(self, state, content):
        from job_agent.model import shared_model
        from job_agent.resume_selection import ResumeSelection, RESUME_SELECTION_PROMPT
        selection = invoke_structured(shared_model(env_path=self._env_path), ResumeSelection,
            RESUME_SELECTION_PROMPT, content)
        return selection.expand(state)

    def __call__(
        self, schema: type[BaseModel], system_message: str, human_message: str
    ) -> BaseModel:
        from job_agent.model import shared_model
        model = shared_model(env_path=self._env_path,
            purpose='extraction' if schema in {ResumeAnalysis, JobAnalysis, SkillAssessment} else None)
        if schema is ResumeAnalysis:
            from job_agent.resume_extraction import ResumeExtraction, RESUME_EXTRACTION_PROMPT
            return invoke_structured(model, ResumeExtraction, RESUME_EXTRACTION_PROMPT, human_message).expand()
        if schema is JobAnalysis:
            from job_agent.job_extraction import ReferencedJobExtraction, REFERENCE_JOB_PROMPT, numbered_sentences
            sentences = numbered_sentences(human_message)
            return invoke_structured(model, ReferencedJobExtraction, REFERENCE_JOB_PROMPT,
                json.dumps(sentences, ensure_ascii=False, separators=(',', ':'))).expand(sentences)
        if schema is SkillAssessment:
            from job_agent.compact_match import CompactSkillAssessment, COMPACT_MATCH_PROMPT
            resume_text, job_text = human_message.removeprefix('Resume analysis:\n').split('\n\nJob analysis:\n', 1)
            resume, job = ResumeAnalysis.model_validate_json(resume_text), JobAnalysis.model_validate_json(job_text)
            content = json.dumps({'evidence': [e.model_dump(mode='json') for e in resume.evidence],
                'requirements': [r.model_dump(mode='json') for r in job.requirements]}, ensure_ascii=False, separators=(',', ':'))
            return invoke_structured(model, CompactSkillAssessment, COMPACT_MATCH_PROMPT, content).expand(resume, job)
        if schema is VerificationResult:
            # Quality is checked deterministically below. Requesting it from
            # the model can reject an otherwise valid factual verdict before
            # that check, e.g. passed=false with no structural issues.
            result = invoke_structured(model, FactualVerificationResult, system_message, human_message)
            return VerificationResult.model_validate(result.model_dump())
        return invoke_structured(model, schema, system_message, human_message)


class JobAgentStepHandler:
    """Execute the validated business steps of the custom agent loop."""

    def __init__(self, analyzer: Analyzer | None = None, *, decisions=None, analysis_cache=None) -> None:
        from agent_runtime.fast_decisions import configured_decisions, FastDecisions
        # Custom analyzers remain isolated unless their caller opts in explicitly.
        self._decisions = decisions if decisions is not None else (
            configured_decisions(scope='career') if analyzer is None else FastDecisions())
        model_analyzer = analyzer or SharedModelAnalyzer()
        self.analysis_cache = analysis_cache
        self._model_analyzer = model_analyzer
        self._analyze = lambda *args, **kwargs: invoke_model(model_analyzer, *args, **kwargs)

    def analysis_cache_namespace(self):
        namespace = getattr(self._model_analyzer,'cache_namespace',None)
        from job_agent.fast_match import MATCH_ROUTING_VERSION
        main = namespace() if callable(namespace) else f'custom:{id(self._model_analyzer)}'
        from job_agent.compact_match import COMPACT_MATCH_PROMPT, CompactSkillAssessment
        import hashlib
        compact = hashlib.sha256(json.dumps([COMPACT_MATCH_PROMPT, CompactSkillAssessment.model_json_schema()], sort_keys=True).encode()).hexdigest()
        return f'{main}:{MATCH_ROUTING_VERSION}:{compact}:{self._decisions.cache_namespace()}'

    def execute(self, step: Step, state: AgentState) -> StepOutcome:
        handlers = {
            Step.VALIDATE_INPUT: self._validate_input,
            Step.ANALYZE_RESUME: self._analyze_resume,
            Step.VALIDATE_EVIDENCE: self._validate_evidence,
            Step.ANALYZE_JOB: self._analyze_job,
            Step.MATCH_SKILLS: self._match_skills,
            Step.WRITE_RESUME: self._write_resume,
            Step.VERIFY_RESUME: self._verify_resume,
            Step.REVISE_RESUME: self._revise_resume,
        }
        handler = handlers.get(step)
        if handler is None:
            raise ValueError(f"Step {step} is not a computation step.")
        kind = {Step.ANALYZE_RESUME: 'resume', Step.ANALYZE_JOB: 'job', Step.MATCH_SKILLS: 'match'}.get(step)
        if self.analysis_cache is None or kind is None:
            return StepOutcome(updates=handler(state))
        def compute():
            updates = handler(state)
            if kind == 'resume':
                self._validate_evidence(state.model_copy(update=updates))
            return {key: value.model_dump(mode='json') if isinstance(value, BaseModel) else value
                    for key, value in updates.items()}
        from job_agent.prompts import PROMPT_VERSION
        from job_agent.schemas import SCHEMA_VERSION
        analyzer_namespace = getattr(self._model_analyzer, 'cache_namespace', None)
        namespace = analyzer_namespace() if callable(analyzer_namespace) else self.analysis_cache_namespace()
        prompt = {'resume': RESUME_PROMPT, 'job': JOB_PROMPT, 'match': MATCH_PROMPT}[kind]
        schema = {'resume': ResumeAnalysis, 'job': JobAnalysis, 'match': SkillAssessment}[kind]
        signature = [namespace, PROMPT_VERSION, SCHEMA_VERSION, prompt, schema.model_json_schema()]
        if kind == 'match':
            # Confirmed Career Evidence is part of the candidate payload, including
            # immutable version IDs. Changing evidence cannot reuse an old score.
            content = [state.resume_analysis.model_dump(mode='json'), state.job_analysis.model_dump(mode='json')]
            signature.append(self.analysis_cache_namespace())
        else:
            content = (state.resume_text if kind == 'resume' else state.job_description).replace('\r\n', '\n').strip()
        updates = self.analysis_cache.get(kind, signature, content, compute)
        if kind == 'resume':
            updates['resume_analysis'] = ResumeAnalysis.model_validate(updates['resume_analysis'])
            self._validate_evidence(state.model_copy(update=updates))
        elif kind == 'job':
            updates['job_analysis'] = JobAnalysis.model_validate(updates['job_analysis'])
        else:
            from job_agent.schemas import SkillMatch
            updates['skill_match'] = SkillMatch.model_validate(updates['skill_match'])
        return StepOutcome(updates=updates)

    @staticmethod
    def _validate_input(state: AgentState) -> dict:
        if not state.resume_text.strip():
            raise ValueError("resume_text must be a non-empty string.")
        if not state.job_description.strip():
            raise ValueError("job_description must be a non-empty string.")
        return {
            "verification": None,
            "revision_feedback": [],
            "revision_count": 0,
            "approved": None,
            "human_feedback": None,
        }

    def _analyze_resume(self, state: AgentState) -> dict:
        analysis = ResumeAnalysis.model_validate(
            self._analyze(ResumeAnalysis, RESUME_PROMPT, state.resume_text.strip())
        )
        return {"resume_analysis": normalize_resume_analysis(analysis)}

    @staticmethod
    def _validate_evidence(state: AgentState) -> dict:
        if state.resume_analysis is None:
            raise ValueError("Resume analysis is required before evidence validation.")
        original = normalize_text(state.resume_text)
        invalid = [
            item.evidence_id
            for item in state.resume_analysis.evidence
            if normalize_text(item.exact_text) not in original
        ]
        if invalid:
            raise ValueError(f"Evidence is not present in the original resume: {invalid}")
        validate_resume_source_metadata(state.resume_analysis, state.resume_text)
        return {}

    def _analyze_job(self, state: AgentState) -> dict:
        analysis = JobAnalysis.model_validate(
            self._analyze(JobAnalysis, JOB_PROMPT, state.job_description.strip())
        )
        return {
            "job_analysis": normalize_job_analysis(
                analysis,
                state.job_description.strip(),
            )
        }

    def _match_skills(self, state: AgentState) -> dict:
        if state.resume_analysis is None or state.job_analysis is None:
            raise ValueError("Resume and job analyses are required before matching skills.")
        resume = state.resume_analysis
        job = state.job_analysis
        content = (
            f"Resume analysis:\n{resume.model_dump_json()}\n\n"
            f"Job analysis:\n{job.model_dump_json()}"
        )
        if self._decisions.enabled or isinstance(self._model_analyzer, SharedModelAnalyzer) or getattr(self._model_analyzer, 'chunked_matching', False):
            from job_agent.fast_match import assess_skills
            assessment = assess_skills(resume, job, self._analyze, self._decisions)
        else:
            assessment = SkillAssessment.model_validate(self._analyze(SkillAssessment, MATCH_PROMPT, content))
        skill_match = normalize_skill_match(resume, job, assessment)
        return {"skill_match": skill_match}

    def _write_resume(self, state: AgentState) -> dict:
        if (
            state.resume_analysis is None
            or state.job_analysis is None
            or state.skill_match is None
        ):
            raise ValueError("Analyses and skill match are required before writing.")
        content = (
            f"SOURCE OF TRUTH - ORIGINAL RESUME:\n{state.resume_text}\n\n"
            f"GROUNDED RESUME EVIDENCE:\n{state.resume_analysis.model_dump_json()}\n\n"
            f"TARGET REQUIREMENTS - JOB ANALYSIS:\n{state.job_analysis.model_dump_json()}\n\n"
            f"SKILL MATCH:\n{state.skill_match.model_dump_json()}\n\n"
            "STRUCTURAL GUIDANCE:\n"
            "Use at most two summary sentences and at most five selected bullets per source entry. "
            "Return target requirement IDs only from the supplied Job Analysis."
        )
        compact_writer = getattr(self._model_analyzer, 'write_resume', None)
        result = invoke_model(compact_writer, state, content) if callable(compact_writer) else self._analyze(TailoredResume, WRITE_RESUME_PROMPT, content)
        draft = normalize_tailored_resume_claim_ids(TailoredResume.model_validate(result))
        draft = normalize_generated_resume_metadata(
            draft,
            state.resume_analysis.source_entries,
            source_resume_text=state.resume_text,
        )
        draft = ensure_foundational_resume_sections(
            draft,
            state.resume_analysis.source_entries,
            {item.evidence_id: item.exact_text for item in state.resume_analysis.evidence},
        )
        cleaned, _ = clean_tailored_resume(draft)
        self._validate_generated_resume(cleaned, state)
        return {"tailored_resume": cleaned}

    @staticmethod
    def _validate_generated_resume(resume: TailoredResume, state: AgentState) -> None:
        if state.resume_analysis is None:
            raise ValueError("Resume analysis is required before source validation.")
        issues = validate_resume_structure(
            resume,
            state.resume_analysis.source_entries,
            known_evidence_ids={
                item.evidence_id for item in state.resume_analysis.evidence
            },
            allow_legacy_source_ids=False,
            source_resume_text=state.resume_text,
        )
        # A generated legacy source ID is a contract violation because it can
        # bypass source ownership entirely. Other source/metadata mistakes are
        # kept in the private draft and handled by VERIFY_RESUME so the bounded
        # revision loop can repair them. They are never projected for review
        # unless deterministic verification passes.
        source_safety_codes = {"legacy_source_entry"}
        failures = [
            item for item in issues
            if item.severity == "error" and item.code in source_safety_codes
        ]
        if failures:
            codes = ", ".join(dict.fromkeys(item.code for item in failures))
            raise ValueError(f"Generated resume failed source validation: {codes}.")

    def _verify_resume(self, state: AgentState) -> dict:
        if state.tailored_resume is None or state.resume_analysis is None:
            raise ValueError("A tailored resume and resume analysis are required.")
        content = (
            f"SOURCE OF TRUTH - ORIGINAL RESUME:\n{state.resume_text}\n\n"
            f"GROUNDED EVIDENCE WITH IDS:\n{state.resume_analysis.model_dump_json()}\n\n"
            "TARGET REQUIREMENTS - JOB DESCRIPTION (NOT EVIDENCE):\n"
            f"{state.job_description}\n\n"
            f"GENERATED CLAIMS TO VERIFY:\n{state.tailored_resume.model_dump_json()}"
        )
        verification = VerificationResult.model_validate(
            self._analyze(VerificationResult, VERIFY_RESUME_PROMPT, content)
        )
        known_ids = {item.evidence_id for item in state.resume_analysis.evidence}
        unsupported = list(verification.unsupported_claims)
        feedback = list(verification.revision_feedback)
        claims = state.tailored_resume.claims()
        for claim in claims:
            if not claim.evidence_ids:
                unsupported.append(
                    UnsupportedClaim(
                        claim=claim.text,
                        reason="The claim does not reference any resume evidence.",
                    )
                )
                feedback.append(
                    f"Remove or rewrite '{claim.text}' with resume evidence IDs."
                )
                continue
            unknown_ids = [item for item in claim.evidence_ids if item not in known_ids]
            if unknown_ids:
                unsupported.append(
                    UnsupportedClaim(
                        claim=claim.text,
                        reason=f"References unknown evidence IDs: {', '.join(unknown_ids)}.",
                    )
                )
                feedback.append(
                    f"Remove or rewrite '{claim.text}' using valid evidence IDs."
                )
        quality_issues = validate_resume_structure(
            state.tailored_resume, state.resume_analysis.source_entries,
            known_evidence_ids=known_ids,
            allow_legacy_source_ids=False,
            source_resume_text=state.resume_text,
        )
        quality = quality_result(quality_issues)
        feedback.extend(quality.revision_feedback)
        if unsupported != verification.unsupported_claims or not quality.passed:
            verification = VerificationResult(
                passed=False, unsupported_claims=unsupported,
                revision_feedback=list(dict.fromkeys(feedback)), quality=quality,
            )
        else:
            verification = VerificationResult.model_validate({
                **verification.model_dump(mode="python"), "quality": quality,
            })
        return {
            "verification": verification,
            "revision_feedback": verification.revision_feedback,
        }

    def _revise_resume(self, state: AgentState) -> dict:
        if (
            state.verification is None
            or state.resume_analysis is None
            or state.job_analysis is None
            or state.tailored_resume is None
        ):
            raise ValueError("Complete resume state is required before revision.")
        from job_agent.resume_selection import remove_unsupported
        repaired = remove_unsupported(state)
        if repaired is not None:
            return {'tailored_resume': repaired, 'verification': None, 'revision_feedback': []}
        feedback = list(state.verification.revision_feedback)
        if state.human_feedback:
            feedback.append(state.human_feedback)
        unsupported_text = {
            normalize_text(item.claim)
            for item in state.verification.unsupported_claims
        }
        unsupported_summary = any(
            normalize_text(claim.text) in unsupported_text
            for section in state.tailored_resume.sections
            if section.section_type == "summary"
            for entry in section.entries
            for claim in entry.bullets
        )
        content = (
            f"SOURCE OF TRUTH - ORIGINAL RESUME:\n{state.resume_text}\n\n"
            f"GROUNDED EVIDENCE WITH IDS:\n{state.resume_analysis.model_dump_json()}\n\n"
            f"CURRENT TAILORED RESUME:\n{state.tailored_resume.model_dump_json()}\n\n"
            f"REVISION FEEDBACK:\n{json.dumps(feedback, ensure_ascii=False)}\n\n"
            "TARGET REQUIREMENTS - JOB ANALYSIS (NOT EVIDENCE):\n"
            f"{state.job_analysis.model_dump_json()}"
        )
        revised = normalize_tailored_resume_claim_ids(TailoredResume.model_validate(
            self._analyze(TailoredResume, REVISE_RESUME_PROMPT, content)
        ))
        revised = normalize_generated_resume_metadata(
            revised,
            state.resume_analysis.source_entries,
            source_resume_text=state.resume_text,
        )
        revised = ensure_foundational_resume_sections(
            revised,
            state.resume_analysis.source_entries,
            {item.evidence_id: item.exact_text for item in state.resume_analysis.evidence},
        )
        if unsupported_summary:
            revised = TailoredResume.model_validate({
                **revised.model_dump(mode="python"),
                "sections": [
                    section.model_dump(mode="python")
                    for section in revised.sections
                    if section.section_type != "summary"
                ],
                "quality_adjustments": [
                    *revised.quality_adjustments,
                    "Removed a summary that remained unsupported after verification.",
                ],
            })
        revised, _ = clean_tailored_resume(revised)
        self._validate_generated_resume(revised, state)
        return {
            "tailored_resume": revised,
            "approved": None,
            "human_feedback": None,
        }
