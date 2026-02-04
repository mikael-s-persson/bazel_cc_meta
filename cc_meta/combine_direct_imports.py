import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="CombineDirectImports",
        description="Combine the direct imports from several files.",
    )
    parser.add_argument("file_list", nargs="*")
    args = parser.parse_args()
    print(args.file_list)
    if len(args.file_list) < 2:
        print(
            "No output file and target name argument provided. Aborting...",
            file=sys.stderr,
        )
        sys.exit(1)

    target_name = args.file_list[-1]
    combined_inc_list = []
    for in_file_name in args.file_list[:-2]:
        in_data = {}
        with open(in_file_name, "r") as f:
            in_data = json.load(f)
        if (
            ("source_file" not in in_data)
            or ("dep_imports" not in in_data)
            or ("sys_imports" not in in_data)
        ):
            print(
                "Missing entries in direct imports json file '{}'. Got {}. Aborting...".format(
                    in_file_name, in_data.keys()
                ),
                file=sys.stderr,
            )
            sys.exit(1)
        if not in_data["source_file"]:
            continue
        combined_inc_list.append(
            {
                "source_file": in_data["source_file"],
                "target": target_name,
                "imports": in_data["dep_imports"],
                "system_imports": in_data["sys_imports"],
            }
        )

    out_file_name = args.file_list[-2]
    with open(out_file_name, "w") as out_file:
        json.dump(
            combined_inc_list,
            out_file,
            indent=2,
        )


if __name__ == "__main__":
    main()
