"""Injectable structured model boundary for interview decisions."""
from __future__ import annotations

from typing import Protocol

from eregion.runtime.interviewer.prompts import ANSWER_SYSTEM, QUESTION_SYSTEM
from eregion.runtime.interviewer.types import (
    ApplicationRequirementAssessment, InterviewAnswerAssessment, InterviewQuestion,
)
from eregion.domain.model import create_model, invoke_structured


class InterviewModelClient(Protocol):
    def question(self, assessment: ApplicationRequirementAssessment, context: str) -> InterviewQuestion: ...
    def classify(self, assessment: ApplicationRequirementAssessment, answer: str, context: str) -> InterviewAnswerAssessment: ...


class SharedInterviewModel:
    def verify_claims(self, claims):
        from eregion.runtime.semantics import SemanticDecisions
        return SemanticDecisions().claims(claims)

    def question(self, assessment: ApplicationRequirementAssessment, context: str) -> InterviewQuestion:
        model = create_model()
        return invoke_structured(model, InterviewQuestion, QUESTION_SYSTEM, context)

    def classify(self, assessment: ApplicationRequirementAssessment, answer: str, context: str) -> InterviewAnswerAssessment:
        model = create_model()
        return invoke_structured(model, InterviewAnswerAssessment, ANSWER_SYSTEM, context)
