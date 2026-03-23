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


def _load_json_or_empty_list(filename):
    result = []
    if filename:
        with open(filename, "r") as f:
            result = json.load(f)
    return result


# Just a heuristic matching for preferring compile commands that compile a source file (not header).
_SOURCE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".c++",
    ".C",
    ".CC",
    ".cp",
    ".CPP",
    ".C++",
    ".CXX",
    ".m",
    ".mm",
    ".M",
    ".cu",
    ".cui",
    ".cl",
    ".clcpp",
    ".s",
    ".asm",
    ".S",
}


def _should_update_comp_cmd(prior_cmd: dict, new_cmd: dict):
    prior_is_src = os.path.splitext(prior_cmd["compile_file"]) in _SOURCE_EXTENSIONS
    new_is_src = os.path.splitext(new_cmd["compile_file"]) in _SOURCE_EXTENSIONS

    # Prefer a command that compiles a source file, instead of parsing a header.
    if new_is_src and not prior_is_src:
        return True
    if prior_is_src and not new_is_src:
        return False

    # Prefer a longer arguments list, more 'specialized'.
    return len(new_cmd["arguments"]) > len(prior_cmd["arguments"])


def _gather_cc_meta(target_list: list, top_dir: str):
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
        # Skip incompatible explicit targets listed (approximate cquery)
        "--skip_incompatible_explicit_targets",
        "--generate_json_trace_profile",
        "--profile=/tmp/bazel_command.profile.gz",
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

    compile_commands_by_file = {}
    combined_all_imports_list = []
    target_to_sys_imports_dict = {}  # Target name to system_imports
    combined_exports_dict = {}  # Target name to exports
    combined_deps_issues_dict = {}  # Target name to deps issues
    combined_ambiguous_imports = []

    targets_by_export = {}

    verbose_output = ("--sandbox_debug" in sys.argv[1:]) or ("-s" in sys.argv[1:])

    for out_ln in target_build_process.stderr.splitlines():
        out_ln_str = out_ln.decode()
        if out_ln_str.startswith("WARNING") or out_ln_str.startswith("ERROR"):
            print(out_ln_str, file=sys.stderr)
        elif out_ln_str.endswith("_cc_meta_compile_commands.json"):
            target_compile_commands = _load_json_or_empty_list(out_ln_str.lstrip())
            for tcmd in target_compile_commands:
                tcmd_file = tcmd["file"]
                compile_commands_by_file.update(
                    {
                        tcmd_file: {
                            "arguments": tcmd["arguments"],
                            "file": tcmd_file,
                            "compile_file": tcmd_file,
                            "directory": top_dir,
                        }
                    }
                )
        elif out_ln_str.endswith("_cc_meta_all_imports.json"):
            all_imports_list = _load_json_or_empty_list(out_ln_str.lstrip())
            combined_all_imports_list.extend(all_imports_list)
        elif out_ln_str.endswith("_cc_meta_imports.json"):
            target_imports_list = _load_json_or_empty_list(out_ln_str.lstrip())
            target_to_sys_imports_dict.update(
                {
                    te["target"]: te["system_imports"]
                    for te in target_imports_list
                    if ("system_imports" in te)
                }
            )
        elif out_ln_str.endswith("_cc_meta_exports.json"):
            target_exports_list = _load_json_or_empty_list(out_ln_str.lstrip())
            combined_exports_dict.update(
                {te["target"]: te for te in target_exports_list}
            )
            for te in target_exports_list:
                for incl_path in te["exports"]:
                    if incl_path not in targets_by_export:
                        targets_by_export.update({incl_path: [te["target"]]})
                    else:
                        targets_by_export.update(
                            {incl_path: targets_by_export[incl_path] + [te["target"]]}
                        )
        elif out_ln_str.endswith("_cc_meta_deps_issues.json"):
            target_deps_issues_list = _load_json_or_empty_list(out_ln_str.lstrip())
            combined_deps_issues_dict.update(
                {
                    di["target"]: di
                    for di in target_deps_issues_list
                    if di["not_found"] or di["unused"]
                }
            )
            for di in target_deps_issues_list:
                if "ambiguous" not in di:
                    continue
                combined_ambiguous_imports.extend(di["ambiguous"])
        elif verbose_output:
            print(out_ln_str, file=sys.stderr)

    for al in combined_all_imports_list:
        comp_src_file = al["source_file"]
        if comp_src_file not in compile_commands_by_file:
            print(
                "WARNING: Missing compile commands for {}!".format(comp_src_file),
                file=sys.stderr,
            )
            continue
        comp_cmd = compile_commands_by_file[comp_src_file]
        for imp_file in al["imports"]:
            new_cmd = {
                "arguments": comp_cmd["arguments"],
                "file": imp_file,
                "compile_file": comp_cmd["compile_file"],
                "directory": top_dir,
            }
            if (imp_file not in compile_commands_by_file) or _should_update_comp_cmd(
                compile_commands_by_file[imp_file], new_cmd
            ):
                compile_commands_by_file.update({imp_file: new_cmd})

    combined_compile_commands = []
    for cmd in compile_commands_by_file.values():
        del cmd["compile_file"]
        combined_compile_commands.append(cmd)

    for target_name, target_sys_imports in target_to_sys_imports_dict.items():
        for imp_file in target_sys_imports:
            if imp_file in targets_by_export:
                print(
                    "\033[33mWARNING:\033[0m Target '{}' includes '{}', which is resolved to a built-in "
                    "or system directory, but is also provided by targets '{}'!\nThere is "
                    "probably a missing dependency. This must be fixed manually. "
                    "Transitive dependencies could affect compilation results.".format(
                        target_name, imp_file, targets_by_export[imp_file]
                    ),
                    file=sys.stderr,
                )

    if len(combined_ambiguous_imports) > 0:
        print(
            "\033[33mWARNING:\033[0m Some includes are ambiguously resolved to a built-in "
            "or system directory, but are also provided by build targets!\nMissing "
            "dependencies cannot be identified accurately. This is a consequence "
            "of using GCC and having system installs (host/exec environment) of "
            "the libraries (headers) involved in the build graph.\nPlease use Clang "
            "and/or use a hermetic build environment (e.g., toolchain, sysroot, "
            "docker, etc.). Here is a list of ambiguous includes:",
            file=sys.stderr,
        )
    for imp_path in frozenset(combined_ambiguous_imports):
        print(
            "\033[33mWARNING:\033[0m Ambiguous include: '{}'".format(imp_path),
            file=sys.stderr,
        )

    print(
        "\r>>> Finished extracting cc-meta-info (got {} files indexed)".format(
            len(compile_commands_by_file)
        )
    )

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


def _get_workspace_exec_root(ws_root):

    # We are looking for the execroot.
    # See https://bazel.build/remote/output-directories
    # We want the path ending in "execroot/_main" in build cache, but we prefer the relative symlink
    # since that would be rewired correctly if the cache directory is moved (e.g., bazel clean).

    # First, attempt to get the bazel-<workspace-name> path (symlink to cache dir).
    info_ws_process = subprocess.run(
        ["bazel", "info", "workspace"],
        capture_output=True,
    )

    if info_ws_process.returncode == 0 and info_ws_process.stdout:
        ws_name = pathlib.Path(info_ws_process.stdout.decode().strip()).name
        ws_rel_exec_root = ws_root / ("bazel-" + ws_name)
        if ws_rel_exec_root.exists():
            return ws_rel_exec_root
        else:
            print(
                "\033[33mWARNING:\033[0m Relative workspace execution root path '{}' does not exist! "
                "(Have you built the project at least once? Is this a remote or read-only workspace?) "
                "Falling back to absolute path in Bazel's current cache, this could be less stable over time.".format(
                    ws_rel_exec_root
                ),
                file=sys.stderr,
            )
    else:
        print(
            "\033[31mERROR:\033[0m Getting workspace name from 'bazel info' failed!\n{}".format(
                info_ws_process.stderr
            ),
            file=sys.stderr,
        )

    # Second, attempt to get the bazel cache execroot directly.
    info_er_process = subprocess.run(
        ["bazel", "info", "execution_root"],
        capture_output=True,
    )

    if info_er_process.returncode == 0 and info_er_process.stdout:
        ws_abs_exec_root = pathlib.Path(info_er_process.stdout.decode().strip())
        if ws_abs_exec_root.exists():
            return ws_abs_exec_root
        else:
            print(
                "\033[33mWARNING:\033[0m Absolute workspace exec root '{}' does not exist! "
                "(Have you built the project at least once? Is this a remote build?) "
                "Falling back to workspace root path, this could affect paths to external dependencies.".format(
                    ws_abs_exec_root
                ),
                file=sys.stderr,
            )
    else:
        print(
            "\033[31mERROR:\033[0m Getting execution_root path from 'bazel info' failed!\n{}".format(
                info_er_process.stderr
            ),
            file=sys.stderr,
        )

    return ws_root


def main():
    workspace_root = _ensure_cwd_is_workspace_root()

    workspace_execroot = _get_workspace_exec_root(workspace_root)

    target_patterns = [
        # Begin: template filled by Bazel
        {target_patterns}  # noqa
        # End:   template filled by Bazel
    ]

    comp_cmds, exports, deps_issues = _gather_cc_meta(
        _get_target_list(target_patterns), str(workspace_execroot)
    )

    if not comp_cmds:
        print(
            ">>> Not writing to compile_commands.json; no sources were found.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Chain output into compile_commands.json
    with open("compile_commands.json", "w") as output_file:
        json.dump(comp_cmds, output_file, indent=2, check_circular=False)

    with open("target_exports.json", "w") as output_file:
        json.dump(exports, output_file, indent=2, check_circular=False)

    with open("dependency_issues.json", "w") as output_file:
        json.dump(deps_issues, output_file, indent=2, check_circular=False)


if __name__ == "__main__":
    main()
