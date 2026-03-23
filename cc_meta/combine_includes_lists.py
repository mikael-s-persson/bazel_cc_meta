import argparse
import json
import sys


def make_includes_list(file_name):
    with open(file_name, "r") as file:
        md_includes_list_str = file.read()
    md_includes_list = md_includes_list_str.replace("\\\n", "").strip().split()
    if len(md_includes_list) < 2:
        return "", []
    if len(md_includes_list) < 3:
        return md_includes_list[1], []
    return md_includes_list[1], md_includes_list[2:]


def main():
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

    target_name = args.file_list[-1]
    combined_inc_list = []
    for in_file_name in args.file_list[:-2]:
        src_file, imp_list = make_includes_list(in_file_name)
        if src_file:
            combined_inc_list.append(
                {"source_file": src_file, "target": target_name, "imports": imp_list}
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
