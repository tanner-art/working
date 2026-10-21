# Factory repository separation

Factory architecture, Registry, workers, delivery loop, guards, telemetry,
dashboard/API and playbooks now have a dedicated private source repository:
[tanner-art/threadline-factory](https://github.com/tanner-art/threadline-factory).

Threadline retains product code, user-data/authentication boundaries, product
planning and original Git history. The September 25 product execution graph
remains at its original path under `docs/factory/` because it is a product contract,
not executable Factory code. Historical commit-pinned planning references still
resolve through preserved Git history. No Registry records are rewritten.

The Factory extraction combines installed reviewed runtime commit
`ec2908d4c62737bec98303db96a7660eb42d5d24` with hosted dashboard and shared auth
helpers from product main `efd2dbae19a69b097fda92a66fe2e1821ed21a14`. The destination's
`EXTRACTION.json` records unchanged source hashes. This avoids losing the newer
delivery loop, which was not in product main.

## Release blocker

This cleanup must remain a draft, unmerged change until the separate hosted
Factory dashboard/API is deployed and verified and the snapshot publisher is
explicitly cut over. Removing `/api/factory-control` before that would break the
existing publisher. See the destination README for the ordered verification and
rollback procedure. Source separation does not prove deployment or runtime cutover.

Installed releases, LaunchAgents, live Registry data, worktrees, credentials,
and user captures were not moved or modified. No Factory activation or product
deployment is part of this extraction. Never merge main as an implementation agent.
