import argparse
import json
import sys


def make_includes_list(file_name):
    with open(file_name, "r") as file:
        md_includes_list_str = file.read()
    md_includes_list = md_includes_list_str.replace("\\\n", "").strip().split()
    if len(md_includes_list) < 3:
        return []
    return md_includes_list[2:]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="CombineIncludesLists",
        description="Combine the include lists for several includes dumps (-MF).",
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

    out_file_name = args.file_list[-2]
    combined_inc_list = []
    for in_file_name in args.file_list[:-2]:
        combined_inc_list.extend(make_includes_list(in_file_name))
    combined_inc_set = sorted(set(combined_inc_list))

    with open(out_file_name, "w") as out_file:
        out_file.write(
            json.dumps(
                [{"target": args.file_list[-1], "imports": combined_inc_set}],
                sort_keys=True,
                indent=2,
            )
        )
