import argparse
import json
import os
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(
        prog="RunClangTidyOnCmd",
        description="Runs clang-tidy on an input compile_commands.json file and a set of source files.",
    )
    parser.add_argument(
        "--cmd-in", required=True, help="Input compile_commands.json from aspect"
    )
    parser.add_argument("--tidy-config", help="Input location for clang-tidy configs")
    parser.add_argument(
        "--tidy-fixes", required=True, help="Output location for clang-tidy fixes"
    )
    parser.add_argument(
        "--tidy-bin", default="/usr/bin/clang-tidy", help="Path to clang-tidy binary"
    )
    parser.add_argument("srcs", nargs="+", help="Source files to lint")
    args = parser.parse_args()

    tidy_bin = "/usr/bin/clang-tidy"  # Default fallback
    if args.tidy_bin != tidy_bin:
        if os.path.exists(args.tidy_bin):
            tidy_bin = args.tidy_bin
        else:
            print(
                f"WARNING: Toolchain's clang-tidy '{args.tidy_bin}' is not found! "
                f"Falling back to system default: {tidy_bin}",
                file=sys.stderr,
            )

    comp_cmds = []
    with open(args.cmd_in, "r") as in_file:
        comp_cmds = json.load(in_file)

    exec_root = os.getcwd()

    for entry in comp_cmds:
        # Patch the directory to be the absolute path of the sandbox execution root
        entry["directory"] = exec_root

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_cmd_file = os.path.join(tmpdir, "compile_commands.json")
        with open(tmp_cmd_file, "w") as out_file:
            json.dump(
                comp_cmds,
                out_file,
                indent=2,
            )

        tidy_cmd = (
            [
                tidy_bin,
                "-p",
                str(tmpdir),
                f"--export-fixes={args.tidy_fixes}",
            ]
            + ([f"--config-file={args.tidy_config}"] if args.tidy_config else [])
            # Don't consider warnings errors when gathering reports.
            + ["--warnings-as-errors=-*"]
            + args.srcs
        )

        # Run clang-tidy and let stdout/stderr pass through to Bazel console
        result = subprocess.run(tidy_cmd, capture_output=True)

        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
        else:
            # Make sure there is something written, Bazel requires actions to generate
            # the files they are declared to output.
            if not os.path.exists(args.tidy_fixes):
                with open(args.tidy_fixes, "w") as out_file:
                    out_file.write("---\n...\n")

        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
