"""
This script takes dependency issues and fixes them using buildozer.
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys

_resolved_targets = {}


def _resolve_target_name(raw_target: str):
    if raw_target in _resolved_targets:
        return _resolved_targets[raw_target]
    target_resolve_process = subprocess.run(
        ["bazel", "query", raw_target],
        capture_output=True,
    )
    resolved_target = raw_target
    if target_resolve_process.returncode == 0:
        resolved_target = target_resolve_process.stdout.decode().strip()
    _resolved_targets[raw_target] = resolved_target
    return resolved_target


def _ensure_cwd_is_workspace_root():
    """Set the current working directory to the root of the workspace."""
    # The `bazel run` command sets `BUILD_WORKSPACE_DIRECTORY` to "the root of the workspace
    # where the build was run." See: https://bazel.build/docs/user-manual#running-executables.
    try:
        workspace_root = pathlib.Path(os.environ["BUILD_WORKSPACE_DIRECTORY"])
    except KeyError:
        print(
            ">>> BUILD_WORKSPACE_DIRECTORY was not found in the environment. Run this tool with `bazel run`.",
            file=sys.stderr,
        )
        sys.exit(1)
    # Change the working directory to the workspace root (assumed by future commands).
    # Although this can fail (OSError/FileNotFoundError/PermissionError/NotADirectoryError),
    # there's no easy way to recover, so we'll happily crash.
    os.chdir(workspace_root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="FixDependencies",
        description="Fix dependency issues with Bazel targets.",
    )
    parser.add_argument("-i", "--issues", default="dependency_issues.json")
    parser.add_argument("-e", "--exports", default="target_exports.json")
    args = parser.parse_args()

    _ensure_cwd_is_workspace_root()

    deps_issues = {}
    with open(args.issues, "r") as f:
        deps_issues = json.load(f)

    exports_by_target = {}
    with open(args.exports, "r") as f:
        exports_by_target = json.load(f)

    targets_by_export = {}
    for t, e in exports_by_target.items():
        for incl_path in e["exports"]:
            if incl_path not in targets_by_export:
                targets_by_export.update({incl_path: [t]})
                continue
            targets_by_export.update({incl_path: targets_by_export[incl_path] + [t]})

    for t, di in deps_issues.items():
        resolved_target = _resolve_target_name(t)
        print("===== Fixing target '{}'".format(resolved_target))
        buildozer_rm = []
        for ut in di["unused"]:
            rut = _resolve_target_name(ut)
            buildozer_rm.append(rut)
        if buildozer_rm:
            buildozer_process = subprocess.run(
                [
                    "buildozer",
                    "-k",
                    "-quiet",
                    "remove deps {}".format(" ".join(buildozer_rm)),
                    resolved_target,
                ]
            )
        buildozer_add = []
        for nf in di["not_found"]:
            if (nf not in targets_by_export) or (not targets_by_export[nf]):
                print("Could not find target for include '{}'!".format(nf))
                new_target = input("Please enter target name (or enter to skip): ")
                if new_target:
                    buildozer_add.append(new_target)
                continue
            if len(targets_by_export[nf]) == 1:
                buildozer_add.append(_resolve_target_name(targets_by_export[nf][0]))
                continue
            resolved_targets = [
                _resolve_target_name(nt) for nt in targets_by_export[nf]
            ]
            print("Multiple targets for include '{}'. Options are:".format(nf))
            for i in range(len(resolved_targets)):
                print("{}: {}".format(i, resolved_targets[i]))
            new_target = input(
                "Please enter option number or target name (or enter to skip): "
            )
            if not new_target:
                continue
            try:
                new_target = int(new_target)
                buildozer_add.append(resolved_targets[new_target])
            except ValueError:
                buildozer_add.append(new_target)
        if buildozer_add:
            buildozer_process = subprocess.run(
                [
                    "buildozer",
                    "-k",
                    "-quiet",
                    "add deps {}".format(" ".join(buildozer_add)),
                    resolved_target,
                ]
            )
