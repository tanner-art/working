"""Fail-closed contract for one exact integrated-feature assurance decision.

An EVALUATION is not an implementation attempt.  Its input is one immutable
Registry evidence row, not a moving branch, a set of package heads, or a
GitHub label.  Live Git/CI checks remain the runner's responsibility.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import pathlib
from dataclasses import dataclass
from typing import Any, Mapping

from scripts.factory_registry.repository import RegistryConflict


SHA = re.compile(r"[0-9a-f]{40}")
HASH = re.compile(r"[0-9a-f]{64}")
PR = re.compile(r"https://github\.com/[^/]+/[^/]+/pull/[1-9]\d*")


@dataclass(frozen=True)
class IntegratedAssuranceInput:
    schema_version: int
    evidence_id: str
    package_id: str
    integrated_commit: str
    integrated_tree: str
    base_commit: str
    target_ref: str
    ordered_parent_shas: tuple[str, ...]
    included_packages: tuple[Mapping[str, Any], ...]
    review_histories: tuple[Mapping[str, Any], ...]
    implementer_workers: tuple[str, ...]
    integration_receipts: tuple[Mapping[str, Any], ...]
    shared_path_handoffs: tuple[Mapping[str, Any], ...]
    acceptance_matrix: tuple[Mapping[str, str], ...]
    ci: Mapping[str, str]
    contract_sha256: str
    review_packet: Mapping[str, Any]
    recorded_at: str


def digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(dict(value), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def parse_assurance_input(evidence: Mapping[str, Any], *, package: Mapping[str, Any],
                          dependencies: tuple[str, ...],
                          review_facts: Mapping[str, Mapping[str, Any]],
                          receipts: Mapping[str, Mapping[str, Any]]) -> IntegratedAssuranceInput:
    """Compare a pinned input with authoritative review and integration rows.

    The caller supplies facts read from the same Registry snapshot/transaction.
    Any missing, changes-requested, or ambiguous ancestor blocks the gate.
    """
    if evidence.get("kind") != "integrated-assurance-input" or evidence.get("package_id") != package.get("id"):
        raise RegistryConflict("ASSURANCE_INPUT_REQUIRED")
    raw = evidence.get("metadata")
    version = raw.get("schema_version") if isinstance(raw, Mapping) else None
    keys = {"schema_version", "package_id", "integrated_commit", "integrated_tree",
            "base_commit", "target_ref", "ordered_parent_shas", "included_packages",
            "acceptance_matrix", "ci", "contract_sha256", "review_packet"}
    if version == 2:
        keys.add("shared_path_handoffs")
    if not isinstance(raw, Mapping) or set(raw) != keys or version not in (1, 2):
        raise RegistryConflict("ASSURANCE_INPUT_INVALID", "schema")
    if package.get("kind") != "EVALUATION" or package.get("lane") != "ASSURANCE" or raw["package_id"] != package.get("id"):
        raise RegistryConflict("ASSURANCE_PACKAGE_MISMATCH")
    if any(not isinstance(raw.get(key), str) or not SHA.fullmatch(raw[key])
           for key in ("integrated_commit", "integrated_tree", "base_commit")):
        raise RegistryConflict("ASSURANCE_INPUT_INVALID", "commit/tree/base")
    if raw["integrated_commit"] == raw["base_commit"] or raw.get("target_ref") != "main":
        raise RegistryConflict("ASSURANCE_INPUT_INVALID", "target")
    if (not isinstance(raw.get("contract_sha256"), str) or not HASH.fullmatch(raw["contract_sha256"])
            or raw["contract_sha256"] != (package.get("provider_diagnostics") or {}).get("queue_contract_sha256")):
        raise RegistryConflict("ASSURANCE_CONTRACT_MISMATCH")
    parents = raw.get("ordered_parent_shas")
    included = raw.get("included_packages")
    if (not isinstance(parents, list) or not parents or any(not isinstance(x, str) or not SHA.fullmatch(x) for x in parents)
            or len(parents) != len(set(parents)) or not isinstance(included, list) or not included):
        raise RegistryConflict("ASSURANCE_INPUT_INVALID", "included parents")
    included_ids: list[str] = []
    included_shas: list[str] = []
    implementers: list[str] = []
    histories: list[Mapping[str, Any]] = []
    receipt_metadata: list[Mapping[str, Any]] = []
    required_fields = {"package_id", "implementation_commit", "pr_url", "review_package_id",
                       "review_outcome_id", "review_evidence_id", "integration_receipt_id"}
    if version == 2:
        required_fields.update({"reviewed_commit", "pr_head_commit", "prior_review_outcome_ids"})
    for item in included:
        if not isinstance(item, Mapping) or set(item) != required_fields:
            raise RegistryConflict("ASSURANCE_INPUT_INVALID", "included package")
        if (not all(isinstance(value, str) and value for key, value in item.items()
                    if key != "prior_review_outcome_ids")
                or not SHA.fullmatch(item["implementation_commit"])
                or not PR.fullmatch(item["pr_url"])):
            raise RegistryConflict("ASSURANCE_INPUT_INVALID", "included identity")
        if version == 2 and (not isinstance(item["prior_review_outcome_ids"], list)
                or any(not isinstance(value, str) or not value for value in item["prior_review_outcome_ids"])
                or len(item["prior_review_outcome_ids"]) != len(set(item["prior_review_outcome_ids"]))
                or not SHA.fullmatch(item["reviewed_commit"])
                or not SHA.fullmatch(item["pr_head_commit"])):
            raise RegistryConflict("ASSURANCE_INPUT_INVALID", "review lineage")
        package_id = item["package_id"]
        review = review_facts.get(package_id)
        receipt = receipts.get(package_id)
        if (not isinstance(review, Mapping) or review.get("state") != "APPROVED"
                or review.get("review_package_id") != item["review_package_id"]
                or review.get("id") != item["review_outcome_id"]
                or item["review_evidence_id"] not in review.get("approval_evidence_ids", ())
                or review.get("reviewed_commit") !=
                    (item["reviewed_commit"] if version == 2 else item["implementation_commit"])
                or review.get("review_pr_url") != item["pr_url"]
                or (version == 2 and (
                    review.get("source_implementation_commit") != item["implementation_commit"]
                    or review.get("prior_review_outcome_ids") != tuple(item["prior_review_outcome_ids"])))
                or not isinstance(receipt, Mapping)
                or receipt.get("id") != item["integration_receipt_id"]
                or receipt.get("kind") != "integration-acceptance"
                or receipt.get("package_id") != package_id):
            raise RegistryConflict("ASSURANCE_ANCESTOR_NOT_APPROVED", package_id)
        if (not isinstance(review.get("implementer_worker_id"), str)
                or not review["implementer_worker_id"]
                or review.get("reviewer_worker_id") == review["implementer_worker_id"]):
            raise RegistryConflict("ASSURANCE_REVIEW_SEPARATION_INVALID", package_id)
        receipt_meta = receipt.get("metadata")
        if (not isinstance(receipt_meta, Mapping)
                or receipt_meta.get("implementation_commit") != item["implementation_commit"]
                or (version == 2 and (
                    receipt_meta.get("reviewed_commit") != item["reviewed_commit"]
                    or receipt_meta.get("pr_head_commit") != item["pr_head_commit"]))
                or receipt_meta.get("pr_url") != item["pr_url"]
                or receipt_meta.get("review_outcome_id") != item["review_outcome_id"]
                or receipt_meta.get("review_evidence_id") != item["review_evidence_id"]
                or not isinstance(receipt_meta.get("merged_main_commit"), str)
                or not SHA.fullmatch(receipt_meta["merged_main_commit"])
                or not isinstance(receipt_meta.get("merged_main_tree"), str)
                or not SHA.fullmatch(receipt_meta["merged_main_tree"])
                or not isinstance(receipt_meta.get("changed_paths"), list)
                or not receipt_meta["changed_paths"]
                or any(not isinstance(path, str) or not path or path.startswith("/")
                       or ".." in path.split("/") for path in receipt_meta["changed_paths"])
                or len(receipt_meta["changed_paths"]) != len(set(receipt_meta["changed_paths"]))):
            raise RegistryConflict("ASSURANCE_INTEGRATION_RECEIPT_INVALID", package_id)
        # A non-ancestral squash/transfer requires a separately reviewed path
        # handoff contract.  This first path refuses to infer patch inclusion.
        if receipt_meta.get("inclusion_mode") != "ancestry":
            raise RegistryConflict("ASSURANCE_PATCH_TRANSFER_UNSUPPORTED", package_id)
        included_ids.append(package_id)
        included_shas.append(receipt_meta["merged_main_commit"])
        historical_implementers = (review.get("implementer_worker_ids") if version == 2
                                   else (review["implementer_worker_id"],))
        if (not isinstance(historical_implementers, (tuple, list))
                or not historical_implementers
                or review["implementer_worker_id"] not in historical_implementers
                or any(not isinstance(worker, str) or not worker for worker in historical_implementers)):
            raise RegistryConflict("ASSURANCE_REVIEW_SEPARATION_INVALID", package_id)
        implementers.extend(historical_implementers)
        if version == 2:
            relation = review.get("remediation_relation")
            if relation is not None and (not isinstance(relation, Mapping)
                    or relation.get("original_package_id") != package_id
                    or relation.get("original_reviewed_commit") != item["implementation_commit"]
                    or relation.get("remediation_review_package_id") != item["review_package_id"]
                    or relation.get("reviewed_commit") != item["reviewed_commit"]
                    or relation.get("merged_main_commit") != receipt_meta["merged_main_commit"]
                    or relation.get("merged_main_tree") != receipt_meta["merged_main_tree"]
                    or relation.get("pr_url") != item["pr_url"]):
                raise RegistryConflict("ASSURANCE_REMEDIATION_RECEIPT_MISMATCH", package_id)
        if version == 2:
            histories.append({"package_id": package_id,
                              "prior_outcomes": list(review.get("prior_review_outcomes", ()))})
        receipt_metadata.append(receipt_meta)
    if (len(included_ids) != len(set(included_ids))
            or not set(dependencies).issubset(included_ids)
            or tuple(parents) != tuple(included_shas)):
        raise RegistryConflict("ASSURANCE_INCLUDED_PACKAGES_MISMATCH")
    handoffs = raw.get("shared_path_handoffs", [])
    if version == 2:
        if not isinstance(handoffs, list):
            raise RegistryConflict("ASSURANCE_SHARED_PATH_HANDOFF_INVALID")
        observed: dict[str, list[str]] = {}
        for package_id, receipt in zip(included_ids, receipt_metadata):
            for path in receipt["changed_paths"]:
                observed.setdefault(path, []).append(package_id)
        repeated = {path: writers for path, writers in observed.items() if len(writers) > 1}
        declared: dict[str, list[str]] = {}
        for handoff in handoffs:
            if (not isinstance(handoff, Mapping) or set(handoff) != {"path", "ordered_writers"}
                    or not isinstance(handoff.get("path"), str)
                    or handoff["path"] in declared
                    or not isinstance(handoff.get("ordered_writers"), list)
                    or any(not isinstance(writer, str) for writer in handoff["ordered_writers"])):
                raise RegistryConflict("ASSURANCE_SHARED_PATH_HANDOFF_INVALID")
            declared[handoff["path"]] = handoff["ordered_writers"]
        if declared != repeated:
            raise RegistryConflict("ASSURANCE_SHARED_PATH_HANDOFF_INVALID")
    matrix = raw.get("acceptance_matrix")
    criteria = package.get("acceptance_criteria") or ()
    if (not criteria or not isinstance(matrix, list) or not matrix or len(matrix) != len(criteria)
            or [item.get("criterion") for item in matrix if isinstance(item, Mapping)] != list(criteria)):
        raise RegistryConflict("ASSURANCE_MATRIX_INCOMPLETE")
    for item in matrix:
        if (not isinstance(item, Mapping) or set(item) != {"criterion", "result", "evidence_id"}
                or item.get("result") != "PASS" or not isinstance(item.get("evidence_id"), str)
                or not item["evidence_id"]):
            raise RegistryConflict("ASSURANCE_MATRIX_INCOMPLETE")
    ci = raw.get("ci")
    if (not isinstance(ci, Mapping) or set(ci) != {"commit", "state", "run_url"}
            or ci.get("commit") != raw["integrated_commit"] or ci.get("state") != "SUCCESS"
            or not isinstance(ci.get("run_url"), str) or not ci["run_url"]):
        raise RegistryConflict("ASSURANCE_CI_REQUIRED")
    packet = raw.get("review_packet")
    if (not isinstance(packet, Mapping) or not isinstance(packet.get("path"), str)
            or not isinstance(packet.get("manifest_sha256"), str)
            or not HASH.fullmatch(packet["manifest_sha256"])):
        raise RegistryConflict("ASSURANCE_REVIEW_PACKET_REQUIRED")
    return IntegratedAssuranceInput(
        schema_version=version,
        evidence_id=str(evidence["id"]), package_id=str(package["id"]),
        integrated_commit=raw["integrated_commit"], integrated_tree=raw["integrated_tree"],
        base_commit=raw["base_commit"], target_ref=raw["target_ref"],
        ordered_parent_shas=tuple(parents), included_packages=tuple(included),
        review_histories=tuple(histories),
        implementer_workers=tuple(implementers),
        integration_receipts=tuple(receipt_metadata),
        shared_path_handoffs=tuple(handoffs),
        acceptance_matrix=tuple(matrix), ci=ci, contract_sha256=raw["contract_sha256"],
        review_packet=packet, recorded_at=str(evidence["recorded_at"]),
    )


def verify_integrated_source(value: IntegratedAssuranceInput, *, repository: pathlib.Path,
                             github, repository_name: str) -> bool:
    """Recheck Git graph, exact main ref, PRs, and CI before provider launch.

    This is an observation, not an authority source: a failure defers the gate.
    All authoritative review/receipt facts were resolved from Registry first.
    """
    def git(*args: str) -> str | None:
        try:
            result = subprocess.run(["git", "-C", str(repository), *args],
                                    capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def ancestor(before: str, after: str) -> bool:
        return git("merge-base", "--is-ancestor", before, after) is not None

    try:
        main = json.loads(github("api", f"repos/{repository_name}/git/ref/heads/main"))
        if (not value.integration_receipts
                or value.integrated_commit != value.integration_receipts[-1]["merged_main_commit"]
                or not ancestor(value.integrated_commit, main["object"]["sha"])):
            return False
        if git("rev-parse", f"{value.integrated_commit}^{{tree}}") != value.integrated_tree:
            return False
        if not ancestor(value.base_commit, value.integrated_commit):
            return False
        prior = value.base_commit
        all_paths: list[str] = []
        if len(value.included_packages) != len(value.integration_receipts):
            return False
        for item, receipt in zip(value.included_packages, value.integration_receipts):
            merged = receipt["merged_main_commit"]
            reviewed = item.get("reviewed_commit", item["implementation_commit"])
            pr_head = item.get("pr_head_commit", reviewed)
            # Historical source and accepted review may be non-ancestral after
            # a cumulative transfer. That requires separate reviewed transfer
            # proof; these fields alone must not assert patch equivalence.
            if (git("rev-parse", f"{merged}^1") != prior
                    or not ancestor(prior, reviewed)
                    or not ancestor(prior, pr_head)
                    or git("rev-parse", f"{reviewed}^{{tree}}") != receipt["merged_main_tree"]
                    or not ancestor(prior, merged) or not ancestor(merged, value.integrated_commit)
                    or not ancestor(value.base_commit, item["implementation_commit"])
                    or not ancestor(item["implementation_commit"], reviewed)
                    or not ancestor(reviewed, merged)
                    or not ancestor(pr_head, merged)
                    or (pr_head != reviewed and not ancestor(pr_head, reviewed))
                    or git("rev-parse", f"{merged}^{{tree}}") != receipt["merged_main_tree"]):
                return False
            step_paths = git("diff", "--name-only", prior, merged)
            if step_paths is None or set(step_paths.splitlines()) != set(receipt["changed_paths"]):
                return False
            prior = merged
            all_paths.extend(receipt["changed_paths"])
            pr = json.loads(github("pr", "view", item["pr_url"], "--repo", repository_name,
                                   "--json", "state,headRefOid,mergeCommit"))
            if (item["pr_url"].rsplit("/pull/", 1)[0] != f"https://github.com/{repository_name}"
                    or not isinstance(pr, Mapping) or not isinstance(pr.get("mergeCommit"), Mapping)
                    or pr.get("state") != "MERGED" or pr.get("headRefOid") != pr_head
                    or pr["mergeCommit"].get("oid") != merged):
                return False
        if value.schema_version == 1 and len(all_paths) != len(set(all_paths)):
            # A transferred shared path requires a separate reviewed handoff.
            return False
        changed = git("diff", "--name-only", value.base_commit, value.integrated_commit)
        if changed is None or set(changed.splitlines()) != set(all_paths):
            return False
        if not re.fullmatch(rf"https://github\.com/{re.escape(repository_name)}/actions/runs/[1-9]\d*",
                            value.ci["run_url"]):
            return False
        run_id = value.ci["run_url"].rsplit("/", 1)[-1]
        run = json.loads(github("run", "view", run_id, "--repo", repository_name,
                                "--json", "headSha,status,conclusion,workflowName,url"))
        return (run.get("headSha") == value.integrated_commit
                and run.get("status") == "completed" and run.get("conclusion") == "success"
                and run.get("workflowName") == "Validate app" and run.get("url") == value.ci["run_url"])
    except (ValueError, KeyError, TypeError, RuntimeError,
            subprocess.TimeoutExpired, OSError):
        return False


def verify_assurance_review_packet(value: IntegratedAssuranceInput,
                                   contract: Mapping[str, Any]) -> None:
    """Check the immutable read-only packet before an operator pins its input."""
    packet = value.review_packet
    root = pathlib.Path(packet["path"])
    try:
        manifest_bytes = (root / "manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        if hashlib.sha256(manifest_bytes).hexdigest() != packet["manifest_sha256"]:
            raise ValueError("manifest changed")
        if (manifest.get("implementation_attempt_id") != f"integrated:{value.integrated_commit}"
                or manifest.get("implementation_commit") != value.integrated_commit
                or manifest.get("base_commit") != value.base_commit
                or manifest.get("files") != packet.get("files")):
            raise ValueError("packet targets another artifact")
        files = manifest["files"]
        if not isinstance(files, dict) or not files:
            raise ValueError("packet files missing")
        for name, expected in files.items():
            if (not isinstance(name, str) or not name or name.startswith("/")
                    or ".." in name.split("/") or not isinstance(expected, str)
                    or not HASH.fullmatch(expected)
                    or hashlib.sha256((root / name).read_bytes()).hexdigest() != expected):
                raise ValueError("packet file changed")
        if json.loads((root / "contract.json").read_text()) != dict(contract):
            raise ValueError("packet contract changed")
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise RegistryConflict("ASSURANCE_REVIEW_PACKET_INVALID") from error
