import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(
        prog="RunDoxygenOnCmd",
        description="Runs doxygen on an input compile_commands.json file and a Doxyfile.",
    )
    parser.add_argument(
        "--cmd-in", required=True, help="Input compile_commands.json from aspect"
    )
    parser.add_argument("--doxyfile", help="Input location for Doxyfile config file")
    parser.add_argument(
        "--doxygen-bin", default="/usr/bin/doxygen", help="Path to doxygen binary"
    )
    args = parser.parse_args()

    doxygen_bin = "/usr/bin/doxygen"  # Default fallback
    if args.doxygen_bin != doxygen_bin:
        if os.path.exists(args.doxygen_bin):
            doxygen_bin = args.doxygen_bin
        else:
            print(
                f"WARNING: Provided doxygen '{args.doxygen_bin}' is not found! "
                f"Falling back to system default: {doxygen_bin}",
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

        tmp_doxyfile_file = os.path.join(tmpdir, "Doxyfile")
        shutil.copyfile(args.doxyfile, tmp_doxyfile_file)
        with open(tmp_doxyfile_file, "a", encoding="utf-8") as out_file:
            out_file.write(
                "\nCLANG_ASSISTED_PARSING = YES\nCLANG_DATABASE_PATH    = {}\n".format(
                    tmpdir
                )
            )

        doxygen_cmd = [
            doxygen_bin,
            str(tmp_doxyfile_file),
        ]

        # Run doxygen and let stdout/stderr pass through to Bazel console
        result = subprocess.run(doxygen_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(result.stdout, file=sys.stderr)
            print(result.stderr, file=sys.stderr)

        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
