"""
This file is the template for the refresh_cc_meta rule.

Interface (after template expansion):
- `bazel run` to regenerate cc metadata for clangd and other tools.
    - No arguments are needed; info from the rule baked into the template expansion.
        - Any arguments passed are interpreted as arguments needed for the builds being analyzed.
    - Requires being run under Bazel so we can access the workspace root environment variable.
- Output: a compile_commands.json for files being compiled by Bazel
- Output: a target_exports.json to list exported includes for each discovered target
- Output: a dependency_issues.json to list dependency issues with each discovered target
"""

import json
import os
import pathlib
import subprocess
import sys


def _get_target_list(target_patterns: list):
    print(">>> Listing targets from: {}".format(" ".join(target_patterns)))

    common_flags = [
        # Shush logging. Just for readability.
        "--ui_event_filters=-info",
        "--noshow_progress",
    ] + sys.argv[1:]

    # Query C++ rules below each target pattern
    target_list = set()
    for target in target_patterns:
        target_list_query = f"kind('cc_.* rule',deps({target}))"
        target_list_cquery_args = [
            "bazel",
            "cquery",
            target_list_query,
        ] + common_flags

        target_list_cquery_process = subprocess.run(
            target_list_cquery_args,
            capture_output=True,
        )

        if target_list_cquery_process.returncode != 0:
            print(target_list_cquery_process.stderr, file=sys.stderr)
            sys.exit(target_list_cquery_process.returncode)

        target_list.update(
            set(
                [
                    s.decode().split()[0]
                    for s in target_list_cquery_process.stdout.splitlines()
                ]
            )
        )

    # Log clear completion messages
    print(f">>> Found {len(target_list)} unique targets from {target}.")

    return list(target_list)


def _load_json_or_empty_list(filename):
    result = []
    if filename:
        with open(filename, "r") as f:
            result = json.loads(f.read())
    return result


def _gather_cc_meta(target_list: list):
    print(">>> Analyzing cc-meta-info...")

    common_flags = [
        # Shush logging. Just for readability.
        "--ui_event_filters=-info",
        "--noshow_progress",
        # Begin: template filled by Bazel
        {cc_meta_aspect},  # noqa
        # End:   template filled by Bazel
        "--output_groups=cc_meta",
        # Show all generated files
        "--show_result=10000",
        # Keep going even if errors occur
        "-k",
    ] + sys.argv[1:]

    target_build_args = (
        [
            "bazel",
            "build",
        ]
        + target_list
        + common_flags
    )

    target_build_process = subprocess.run(
        target_build_args,
        capture_output=True,
    )

    if target_build_process.returncode != 0:
        print("Failed to build all targets. Results will be partial.", file=sys.stderr)

    combined_compile_commands = []
    combined_exports_dict = {}  # Target name to exports
    combined_deps_issues_dict = {}  # Target name to deps issues

    for out_ln in target_build_process.stderr.splitlines():
        out_ln_str = out_ln.decode()
        if out_ln_str.startswith("WARNING") or out_ln_str.startswith("ERROR"):
            print(out_ln_str, file=sys.stderr)
        elif out_ln_str.endswith("_compile_commands.json"):
            target_compile_commands = _load_json_or_empty_list(out_ln_str.lstrip())
            combined_compile_commands.extend(target_compile_commands)
        elif out_ln_str.endswith("_exports.json"):
            target_exports_list = _load_json_or_empty_list(out_ln_str.lstrip())
            combined_exports_dict.update(
                {te["target"]: te for te in target_exports_list}
            )
        elif out_ln_str.endswith("_deps_issues.json"):
            target_deps_issues_list = _load_json_or_empty_list(out_ln_str.lstrip())
            combined_deps_issues_dict.update(
                {
                    di["target"]: di
                    for di in target_deps_issues_list
                    if di["not_found"] or di["unused"]
                }
            )

    print("\r>>> Finished extracting cc-meta-info")

    return combined_compile_commands, combined_exports_dict, combined_deps_issues_dict


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
    return workspace_root


if __name__ == "__main__":
    workspace_root = _ensure_cwd_is_workspace_root()

    target_patterns = [
        # Begin: template filled by Bazel
        {target_patterns}  # noqa
        # End:   template filled by Bazel
    ]

    comp_cmds, exports, deps_issues = _gather_cc_meta(_get_target_list(target_patterns))

    if not comp_cmds:
        print(
            ">>> Not writing to compile_commands.json; no sources were found.",
            file=sys.stderr,
        )
        sys.exit(1)

    for i in range(len(comp_cmds)):
        comp_cmds[i].update({"directory": str(workspace_root)})

    # Chain output into compile_commands.json
    with open("compile_commands.json", "w") as output_file:
        json.dump(comp_cmds, output_file, indent=2, check_circular=False)

    with open("target_exports.json", "w") as output_file:
        json.dump(exports, output_file, indent=2, check_circular=False)

    with open("dependency_issues.json", "w") as output_file:
        json.dump(deps_issues, output_file, indent=2, check_circular=False)
