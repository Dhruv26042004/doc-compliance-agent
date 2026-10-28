from datetime import date
from enum import StrEnum

import yaml
from pydantic import BaseModel, Field, model_validator

from app.config import get_settings


class RuleKind(StrEnum):
    REQUIRED = "required"  # document violates if no clause matches
    PROHIBITED = "prohibited"  # any matching clause is a violation
    REVIEW = "review"  # any matching clause is flagged for a lawyer


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Rule(BaseModel):
    id: str = Field(pattern=r"^R-\d{2}$")
    title: str
    kind: RuleKind
    severity: Severity
    definition: str
    matches: list[str] = Field(min_length=1)
    does_not_match: list[str] = Field(min_length=1)
    edge_notes: str = ""
    cuad_categories: list[str] = Field(min_length=1)


class Policy(BaseModel):
    policy_id: str
    version: int
    effective_date: date
    rules: list[Rule]

    @model_validator(mode="after")
    def _unique_rules(self) -> "Policy":
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule ids")
        cats = [c for r in self.rules for c in r.cuad_categories]
        if len(cats) != len(set(cats)):
            raise ValueError("a CUAD category is mapped to more than one rule")
        return self

    def rule(self, rule_id: str) -> Rule:
        return next(r for r in self.rules if r.id == rule_id)

    def category_to_rule(self) -> dict[str, str]:
        return {c: r.id for r in self.rules for c in r.cuad_categories}


def load_policy(version: int = 1) -> Policy:
    path = get_settings().data_dir / "policy" / f"policy_v{version}.yaml"
    return Policy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
