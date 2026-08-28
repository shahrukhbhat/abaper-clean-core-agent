# ADR 0003: `requirements.txt` is a first-class deliverable, not cluster-managed

- **Status**: Accepted
- **Date**: 2026-08-21
- **Deciders**: agent owners (Shahrukh Bhat)

## Context

The `sap-agent-bootstrap` skill documents that Python dependencies are
"installed in the cluster via CI/CD" and **not** installed locally — a Joule
runtime assumption where the platform provisions the environment. Under that
assumption `requirements.txt` is advisory at best.

Our canonical path is a self-managed CF MTA (ADR 0001) built with the Python
buildpack, and we also run the agent and its test suite locally. In both cases the
dependency list must be complete and correct or the app fails to build/start.

## Decision

Treat `assets/abap-clean-core-agent/requirements.txt` as a **real, complete
deliverable** for both the CF buildpack and local development/test.

- It must include everything `main.py` (and the rest of `app/`) imports —
  including `starlette`, `uvicorn`, `click`, `httpx`, `a2a-sdk`, the
  LangChain/LangGraph stack, `opentelemetry-instrumentation-starlette`, and
  `cfenv` (used by `mcp_auth.py` to read `VCAP_SERVICES` for the Destination
  binding — see ADR 0002).
- `create_agent` is imported from `langchain.agents` (never the deprecated
  `create_react_agent`). If a pinned release does not export it, resolve the
  correct import and pin the matching version rather than leaving a broken import.
- `sap_cloud_sdk.*` is **not on public PyPI**; the private-index requirement
  (whether it ships inside `generative-ai-hub-sdk` or needs `PIP_EXTRA_INDEX_URL`
  / `.pip.conf`) must be documented so both the buildpack and local installs can
  resolve it.
- Any newly imported dependency is added to `requirements.txt` in the same change.

## Consequences

- `pip install -r requirements.txt` works locally (validated on Python 3.13 in a
  virtualenv), enabling offline unit/integration tests.
- The CF Python buildpack has a complete manifest to build from.
- Contributors on machines whose default `python3` is too old (e.g. 3.9) must use
  a 3.13 interpreter to install and run — the modern syntax in the codebase does
  not parse on older versions.

## References

- `specification/guidelines-agent.md` → "Skill Usage Policy" (dependency-note override), "Key Constraints"
- `specification/plans/cf-aicore-deployment-plan.md` → "Runtime dependencies & buildpack artifacts", Review Feedback #2
- `assets/abap-clean-core-agent/requirements.txt`
