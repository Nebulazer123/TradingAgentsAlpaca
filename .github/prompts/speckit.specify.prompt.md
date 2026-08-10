---
---
agent: speckit.specify
title: "Speckit: Specify"
description: "Create a focused implementation spec using .specify/templates and repository context."
---

Using repository files and `.specify/templates/spec-template.md`, generate a clear implementation `spec` describing the intended feature or component requested by the user. Produce output suitable for feeding into `/speckit.plan` and `/speckit.tasks` steps. Ask for missing inputs (scope, constraints) before writing the final spec.

Base the spec only on repository facts and `.specify` templates. Do not invent product requirements.

