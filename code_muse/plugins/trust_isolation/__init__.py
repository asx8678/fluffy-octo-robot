"""Security, Trust & Isolation Model for Blackboard + Experience Store.

This plugin implements the Phase 0 prerequisite security model (z30.0)
required before blackboard (4.2) and experience store (4.3) can be built.

Key concepts:
- **Scope**: every artifact/capsule lives in a scope (repo, workspace, or
  explicit collaboration group). Cross-scope reads are denied by default.
- **Provenance**: every artifact carries who created it (agent identity +
  task context) and when. This enables poisoning detection and audit.
- **Capabilities**: tools that read/write the blackboard or experience
  store must declare their required capabilities. Undeclared access is
  denied.
- **Guardrails**: at least one guardrail is enforced in code — scope
  enforcement + provenance tagging — before 4.2/4.3 code ships.

See THREAT_MODEL.md for the threat analysis.
"""
