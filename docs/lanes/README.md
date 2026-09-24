# Factory lane playbooks

Lane playbooks are the authoritative operating guides for capability specializations. Worker identity, provider, and model do not permanently determine a lane.

Before accepting a package, every worker must read:

1. `AGENTS.md`;
2. the assigned lane playbook;
3. the work-package specification;
4. the canonical architecture and decision documents named by that package.

The worker records: `Lane scope confirmed: <LANE>; package <ID>; required capabilities <list>.`

Before completion, the worker self-checks against the same playbook and reports required evidence. An independent reviewer uses the implementation lane's playbook plus the ASSURANCE playbook.

Repeatable, material lessons may be proposed as playbook changes. An isolated incident should remain attempt evidence unless recurrence or impact justifies a durable rule.

Future lanes such as MARKETING, DATA, and SECURITY must receive a playbook before tasks can require them.

Orchestra is a coordinator and adjudicator, not another implementation lane. It decomposes and schedules work, maintains executable backlog, resolves conflicts, protects reserve, and requests merge decisions. It must not routinely claim implementation packages or act as the sole reviewer.
