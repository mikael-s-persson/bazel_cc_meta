"""
This file is the template for the gather_clang_tidy_issues rule.

Interface (after template expansion):
- `bazel run` to regenerate a combined set of fixes from clang-tidy.
    - No arguments are needed; info from the rule is baked into it by template expansion.
        - Any unknown arguments passed are forwarded to the builds being analyzed.
    - Requires being run under Bazel so we can access the workspace root environment variable.
- Output: clang_tidy_fixes.yaml for all files being compiled by Bazel
- Output: (optional) a Code Climate JSON file suitable for gitlab's CI issue reporting system
- Output: (optional) a SARIF JSON file suitable for github's CI issue reporting system
- Arguments:
  --gather-into-yaml: Output path for combined yaml (default: clang_tidy_fixes.yaml).
  --no-gather-into-yaml: Suppress output of the combined yaml.
  --gather-into-gitlab: Output path for a Code Climate JSON for gitlab CI (default: none).
  --gather-into-github: Output path for a SARIF JSON file for github CI (default: none).
"""

import argparse
import hashlib
import json
import os
import re
import pathlib
import subprocess
import sys
from cc_meta.yaml_wrapper import yaml_safe_load_all, yaml_safe_dump
from functools import lru_cache


def _get_target_list(target_patterns: list, unknown_args: list):
    print(">>> Listing targets from: {}".format(" ".join(target_patterns)))

    common_flags = [
        # Shush logging. Just for readability.
        "--ui_event_filters=-info",
        "--noshow_progress",
    ] + unknown_args

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
            encoding="utf-8",
        )

        if target_list_cquery_process.returncode != 0:
            print(target_list_cquery_process.stderr, file=sys.stderr)
            sys.exit(target_list_cquery_process.returncode)

        target_list.update(
            set([s.split()[0] for s in target_list_cquery_process.stdout.splitlines()])
        )

    # Log clear completion messages
    print(f">>> Found {len(target_list)} unique targets from {target}.")

    return list(target_list)


def _get_bazel_exec_root():
    info_er_process = subprocess.run(
        ["bazel", "info", "execution_root"],
        capture_output=True,
        encoding="utf-8",
    )

    if info_er_process.returncode == 0 and info_er_process.stdout:
        return pathlib.Path(info_er_process.stdout.strip())
    else:
        print(
            "\033[31mERROR:\033[0m Getting execution_root path from 'bazel info' failed!\n{}".format(
                info_er_process.stderr
            ),
            file=sys.stderr,
        )
        sys.exit(1)


def _clang_tidy_version(target_list: list, unknown_args: list):
    print(">>> Identifying clang-tidy version")

    common_flags = [
        # Shush logging. Just for readability.
        "--ui_event_filters=-info",
        "--noshow_progress",
    ] + unknown_args

    # Query targets from the list to find the underlying cc_toolchain
    # Stop as soon as we probably found clang-tidy
    tidy_bin = ""
    for target in target_list:
        target_toolchain_query = f"kind('cc_toolchain',deps({target}))"
        target_toolchain_exec = '--starlark:expr=getattr(providers(target).get(([p for p in providers(target).keys() if "CcToolchainInfo" in str(p)] or [None])[0], None), "compiler_executable", "not_found")'
        target_toolchain_cquery_args = [
            "bazel",
            "cquery",
            target_toolchain_query,
            "--output=starlark",
            target_toolchain_exec,
        ] + common_flags

        target_toolchain_cquery_process = subprocess.run(
            target_toolchain_cquery_args,
            capture_output=True,
            encoding="utf-8",
        )

        if target_toolchain_cquery_process.returncode == 0:
            for ln in target_toolchain_cquery_process.stdout.splitlines():
                ln_stripped = ln.strip()
                if len(ln_stripped) == 0 or ln_stripped == "not_found":
                    continue
                comp_path = pathlib.Path(ln_stripped)
                # If absolute, then we're using the system's clang-tidy
                if comp_path.is_absolute():
                    tidy_bin = "clang-tidy"
                else:
                    tidy_bin = _get_bazel_exec_root() / comp_path.with_name(
                        "clang-tidy"
                    )
                    if not tidy_bin.exists():
                        print(
                            "\033[31mERROR:\033[0m Failed to find clang-tidy executable based on bazel's toolchain!",
                            file=sys.stderr,
                        )
                        sys.exit(1)
                    tidy_bin = str(tidy_bin)

        if len(tidy_bin) > 0:
            break

    if len(tidy_bin) == 0:
        print(
            "\033[31mERROR:\033[0m Failed to find clang-tidy executable based on bazel's toolchain!",
            file=sys.stderr,
        )
        sys.exit(1)

    info_version_process = subprocess.run(
        [tidy_bin, "--version"],
        capture_output=True,
        encoding="utf-8",
    )

    version_number = ""
    if info_version_process.returncode == 0 and info_version_process.stdout:
        version_pattern = r"\d+(?:\.\d+)+"
        for ln in info_version_process.stdout.splitlines():
            version_match = re.search(version_pattern, ln)
            if version_match:
                version_number = version_match.group(0)
                break
        if len(version_number) == 0:
            print(
                "\033[31mERROR:\033[0m No version number found in output:\n{}".format(
                    info_version_process.stdout
                ),
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print(
            "\033[31mERROR:\033[0m Getting version from clang-tidy failed!\n{}".format(
                info_version_process.stderr
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    # Log clear completion messages
    print(f">>> Detected version {version_number} of clang-tidy.")

    return version_number


def _dashed_to_pascal(text: str) -> str:
    return "".join(word.capitalize() for word in text.split("-"))


def _load_yaml_or_empty_list(filename):
    result = []
    if filename:
        with open(filename, "r", encoding="utf-8") as f:
            result = list(yaml_safe_load_all(f))
    if not result:
        return []
    return result


# Set maxsize to the maximum number of file contents you want to keep in memory
@lru_cache(maxsize=32)
def _read_file_cached(file_path: str) -> bytes:
    with open(file_path, "rb") as f:
        return f.read()


def _file_offset_to_loc(content: bytes, file_offset: int):
    line = content[0:file_offset].count(b"\n") + 1
    col = file_offset - max(0, content.rfind(b"\n", 0, file_offset))
    return line, col


def _gather_all_issues(target_list: list, unknown_args: list):
    print(">>> Generating clang-tidy reports...")

    common_flags = [
        # Shush logging. Just for readability.
        "--ui_event_filters=-info",
        "--noshow_progress",
        # Begin: template filled by Bazel
        {clang_tidy_aspect},  # noqa
        # End:   template filled by Bazel
        "--output_groups=clang_tidy_fixes",
        # Show all generated files
        "--show_result=10000",
        # Keep going even if errors occur
        "-k",
        # Skip incompatible explicit targets listed (approximate cquery)
        "--skip_incompatible_explicit_targets",
    ] + unknown_args

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

    combined_tidy_diags = []
    seen_diags = set()

    verbose_output = ("--sandbox_debug" in unknown_args) or ("-s" in unknown_args)
    diags_count = 0

    for out_ln in target_build_process.stderr.splitlines():
        out_ln_str = out_ln.decode()
        if out_ln_str.startswith("WARNING") or out_ln_str.startswith("ERROR"):
            print(out_ln_str, file=sys.stderr)
        elif out_ln_str.endswith("_cc_meta_clang_tidy_fixes.yaml"):
            tidy_issues = _load_yaml_or_empty_list(out_ln_str.lstrip())
            for tidy_mainfile in tidy_issues:
                if (not tidy_mainfile) or ("Diagnostics" not in tidy_mainfile):
                    continue
                new_main_file_tidy_diags = {"Diagnostics": []}
                new_main_file_path = None
                for diag in tidy_mainfile["Diagnostics"]:
                    diag.pop("BuildDirectory", None)
                    diag_msg = diag["DiagnosticMessage"]
                    diag_msg["FilePath"] = diag_msg["FilePath"].removeprefix("./")
                    if "Replacements" in diag_msg:
                        for rep in diag_msg["Replacements"]:
                            if "FilePath" in rep:
                                rep["FilePath"] = rep["FilePath"].removeprefix("./")
                    rule_name = diag.get("DiagnosticName", "unknown-check")
                    primary_path = diag_msg["FilePath"]
                    primary_loc = diag_msg.get("FileOffset", 0)
                    diag_id = f"{rule_name}:{primary_path}:{primary_loc}"
                    if diag_id not in seen_diags:
                        if not new_main_file_path:
                            new_main_file_path = primary_path
                        new_main_file_tidy_diags["Diagnostics"].append(diag)
                        diags_count += 1
                        seen_diags.add(diag_id)
                if new_main_file_path:
                    new_main_file_tidy_diags["MainSourceFile"] = new_main_file_path
                    combined_tidy_diags.append(new_main_file_tidy_diags)
        elif verbose_output:
            print(out_ln_str, file=sys.stderr)

    print(
        "\r>>> Finished extracting clang-tidy reports (got {} fixes)".format(
            diags_count
        )
    )

    return combined_tidy_diags


def _ensure_cwd_is_workspace_root():
    """Set the current working directory to the root of the workspace."""
    # The `bazel run` command sets `BUILD_WORKSPACE_DIRECTORY` to "the root of the workspace
    # where the build was run." See: https://bazel.build/docs/user-manual#running-executables.
    try:
        workspace_root = pathlib.Path(os.environ["BUILD_WORKSPACE_DIRECTORY"])
    except KeyError:
        print(
            ">>> BUILD_WORKSPACE_DIRECTORY was not found in the environment. "
            + "Run this tool with `bazel run`.",
            file=sys.stderr,
        )
        sys.exit(1)
    # Change the working directory to the workspace root (assumed by future commands).
    # Although this can fail (OSError/FileNotFoundError/PermissionError/NotADirectoryError),
    # there's no easy way to recover, so we'll happily crash.
    os.chdir(workspace_root)
    return workspace_root


def main():
    parser = argparse.ArgumentParser(
        prog="GatherClangTidyIssues",
        description="Gathers clang-tidy fixes from a Bazel aspect.",
    )
    parser.add_argument(
        "--gather-into-yaml",
        default="clang_tidy_fixes.yaml",
        help="Output path for combined yaml.",
    )
    parser.add_argument(
        "--no-gather-into-yaml",
        action="store_true",
        help="Do not output a combined yaml.",
    )
    parser.add_argument(
        "--gather-into-gitlab", help="Output Code Climate JSON for gitlab CI"
    )
    parser.add_argument("--gather-into-github", help="Output SARIF file for github CI")
    args, unknown_args = parser.parse_known_args()

    workspace_root = _ensure_cwd_is_workspace_root()

    target_patterns = [
        # Begin: template filled by Bazel
        {target_patterns}  # noqa
        # End:   template filled by Bazel
    ]

    target_list = _get_target_list(target_patterns, unknown_args)
    tidy_version = "0.0.0"
    if args.gather_into_github:
        # Github requires a version number for the tool
        tidy_version = _clang_tidy_version(target_list, unknown_args)
    tidy_issues = _gather_all_issues(target_list, unknown_args)

    if not tidy_issues:
        print(">>> Not writing outputs; no issues were found.")
        sys.exit(0)

    # Output a combined yaml, unless user told us not too.
    if not args.no_gather_into_yaml:
        with open(args.gather_into_yaml, "w", encoding="utf-8") as out_file:
            for main_file_diags in tidy_issues:
                out_file.write("---\n")
                yaml_safe_dump(main_file_diags, out_file, sort_keys=False)
            out_file.write("...\n")

    # Attempt to augment the tidy issues locations with line/column
    if args.gather_into_gitlab or args.gather_into_github:
        # Flatten the tidy issues, we don't need the main-source-file breakdown.
        flat_tidy_issues = [diag for mf in tidy_issues for diag in mf["Diagnostics"]]
        for diag in flat_tidy_issues:
            rule_name = diag.get("DiagnosticName", "unknown-check")
            diag_msg = diag["DiagnosticMessage"]
            primary_path = diag_msg["FilePath"]
            primary_loc = diag_msg.get("FileOffset", 0)
            if not os.path.exists(primary_path):
                diag_msg["Fingerprint"] = hashlib.shake_128(
                    f"{primary_path}:{primary_loc}:{rule_name}".encode("utf-8")
                ).hexdigest(8)
                continue
            content = _read_file_cached(primary_path)
            primary_line, primary_col = _file_offset_to_loc(content, primary_loc)
            diag_msg["FileLine"] = primary_line
            diag_msg["FileCol"] = primary_col
            primary_slice = content[
                max(primary_loc - primary_col, primary_loc - 16) : min(
                    primary_loc + 16, len(content)
                )
            ]
            # Try to get a unique but stable fingerprint
            # The most unique is probably a slice of code around the issue
            diag_msg["Fingerprint"] = hashlib.shake_128(
                f"{primary_path}:{primary_slice}:{rule_name}".encode("utf-8")
            ).hexdigest(8)
            if "Replacements" in diag_msg:
                for rep in diag_msg["Replacements"]:
                    if "ReplacementText" not in rep:
                        continue
                    fix_path = rep["FilePath"]
                    if not os.path.exists(fix_path):
                        continue
                    fix_loc = rep.get("Offset", 0)
                    fix_content = _read_file_cached(fix_path)
                    fix_line, fix_col = _file_offset_to_loc(fix_content, fix_loc)
                    rep["FileLine"] = fix_line
                    rep["FileCol"] = fix_col
            if "Ranges" in diag_msg:
                for rang in diag_msg["Ranges"]:
                    fix_path = rang["FilePath"]
                    if not os.path.exists(fix_path):
                        continue
                    fix_loc = rang.get("FileOffset", 0)
                    fix_content = _read_file_cached(fix_path)
                    fix_line, fix_col = _file_offset_to_loc(fix_content, fix_loc)
                    rang["FileLine"] = fix_line
                    rang["FileCol"] = fix_col

    if args.gather_into_gitlab:
        gitlab_issues = []
        for diag in flat_tidy_issues:
            # Extract the primary location info
            rule_name = diag.get("DiagnosticName", "unknown-check")
            diag_msg = diag["DiagnosticMessage"]
            issue_line = diag_msg.get("FileLine", 1)
            issue_col = diag_msg.get("FileCol", 1)
            issue_path = diag_msg.get("FilePath", "")
            message_text = diag_msg.get("Message", "")

            # GitLab Code Quality format
            issue = {
                "type": "issue",
                "description": f"{message_text} [{rule_name}] "
                + f"(at {issue_path}:{issue_line}:{issue_col})",
                "categories": ["Style"],
                "check_name": rule_name,
                "fingerprint": diag_msg["Fingerprint"],
                "severity": "major",
                "location": {
                    "path": issue_path,
                    "lines": {"begin": issue_line, "end": issue_line},
                },
            }
            if "Replacements" in diag_msg:
                for rep in diag_msg["Replacements"]:
                    if "ReplacementText" not in rep:
                        continue
                    fix_line = rep.get("FileLine", 1)
                    fix_col = rep.get("FileCol", 1)
                    fix_path = rep["FilePath"]
                    fix_rep = rep["ReplacementText"]
                    issue[
                        "description"
                    ] += f"\n###Suggested Fix\n{fix_path}:{fix_line}:{fix_col}: {fix_rep}"
            if "Ranges" in diag_msg:
                for rang in diag_msg["Ranges"]:
                    fix_line = rang.get("FileLine", 1)
                    fix_col = rang.get("FileCol", 1)
                    fix_len = rang.get("Length", 0)
                    fix_path = rang["FilePath"]
                    issue[
                        "description"
                    ] += f"\nAt {fix_path}:{fix_line}:{fix_col}-{fix_col + fix_len}"
            gitlab_issues.append(issue)
        with open(args.gather_into_gitlab, "w", encoding="utf-8") as out_file:
            json.dump(gitlab_issues, out_file, indent=2)

    if args.gather_into_github:
        github_issues = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "clang-tidy",
                            "version": tidy_version,
                            "semanticVersion": tidy_version,
                            "informationUri": "https://clang.llvm.org/extra/clang-tidy/",
                            "rules": [],
                        }
                    },
                    "results": [],
                }
            ],
        }
        seen_rules = set()
        rules_list = github_issues["runs"][0]["tool"]["driver"]["rules"]
        github_results = github_issues["runs"][0]["results"]

        for diag in flat_tidy_issues:
            rule_name = diag.get("DiagnosticName", "unknown-check")
            diag_msg = diag.get("DiagnosticMessage", {})
            issue_path = diag_msg.get("FilePath", "")
            issue_line = diag_msg.get("FileLine", 1)
            issue_col = diag_msg.get("FileCol", 1)
            message_text = diag_msg.get("Message", "")

            # Populate the rule registry if newly encountered
            if rule_name not in seen_rules:
                # Fill in all the info that this kitchen-sink standard requires.
                rules_list.append(
                    {
                        "id": rule_name,
                        "name": _dashed_to_pascal(rule_name),
                        "shortDescription": {
                            "text": f"Clang-Tidy violation: {rule_name}."
                        },
                        "fullDescription": {
                            "text": f"Clang-Tidy violation: {rule_name}."
                        },
                        "helpUri": "https://clang.llvm.org/extra/clang-tidy/checks/list.html",
                        "help": {"text": f"Clang-Tidy violation: {rule_name}."},
                    }
                )
                seen_rules.add(rule_name)

            if "Replacements" in diag_msg:
                for rep in diag_msg["Replacements"]:
                    if "ReplacementText" not in rep:
                        continue
                    fix_line = rep.get("FileLine", 1)
                    fix_col = rep.get("FileCol", 1)
                    fix_path = rep["FilePath"]
                    fix_rep = rep["ReplacementText"]
                    message_text += f"\n\n**Suggested Fix**\n`{fix_path}:{fix_line}:{fix_col}: {fix_rep}`"

            if "Ranges" in diag_msg:
                for rang in diag_msg["Ranges"]:
                    fix_line = rang.get("FileLine", 1)
                    fix_col = rang.get("FileCol", 1)
                    fix_len = rang.get("Length", 0)
                    fix_path = rang["FilePath"]
                    message_text += f"\n\n**Range**\n`{fix_path}:{fix_line}:{fix_col}-{fix_col + fix_len}`"

            # Append the unique result node
            sarif_result = {
                "ruleId": rule_name,
                "message": {"text": message_text},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": issue_path},
                            "region": {
                                "startLine": issue_line,
                                "startColumn": issue_col,
                            },
                        }
                    }
                ],
                "partialFingerprints": {
                    "primaryLocationLineHash": diag_msg["Fingerprint"]
                },
            }
            github_results.append(sarif_result)

        with open(args.gather_into_github, "w", encoding="utf-8") as out_file:
            json.dump(github_issues, out_file, indent=2)


if __name__ == "__main__":
    main()
