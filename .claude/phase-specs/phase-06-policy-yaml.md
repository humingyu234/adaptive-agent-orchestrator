# Phase 6 - Policy YAML

Goal: Make basic control policy declarative.

## Allowed Files

```text
src/orchestrator/policy.py
examples/policy.yaml
tests/test_policy.py
```

## Policy Concepts

```yaml
mode: controlled

files:
  allowed:
    - src/orchestrator/**
    - tests/**
  protected:
    - .env
    - secrets/**
    - outputs/**

checks:
  required:
    - pytest

human_review:
  required_for:
    - high_risk_tool
    - protected_file_change
    - failed_tests

tools:
  shell:
    risk_level: high
  search:
    risk_level: low
```

## Required Tests

- allowed files pass
- protected files are blocked or require human review
- high-risk tool requires human review
- missing policy uses safe defaults

## Commands

```bash
python -m pytest tests/test_policy.py
python -m pytest
```
