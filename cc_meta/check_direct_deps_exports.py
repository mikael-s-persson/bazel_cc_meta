import argparse
import json
import sys


def read_json_file(file_name):
    with open(file_name, "r") as file:
        content_str = file.read()
    return json.loads(content_str)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="CheckDirectDepsExports",
        description="Check the include lists for several includes dumps (-MF).",
    )
    parser.add_argument("file_list", nargs="*")
    args = parser.parse_args()
    print(args.file_list)
    if len(args.file_list) < 2:
        print(
            "No target imports and output file provided. Aborting...", file=sys.stderr
        )
        sys.exit(1)

    out_file_name = args.file_list[-1]
    deps_exports = []
    for in_file_name in args.file_list[:-2]:
        dep_exports = read_json_file(in_file_name)
        if isinstance(dep_exports, list):
            deps_exports.extend(dep_exports)
        else:
            deps_exports.append(dep_exports)

    exports_to_deps = []
    for dep_exports in deps_exports:
        for dep_export in dep_exports["exports"]:
            exports_to_deps.append((dep_export, dep_exports["target"]))
    exports_to_deps.sort()

    # Expecting only one target, but why not support a list (stored as a list anyway)
    targets_imports = read_json_file(args.file_list[-2])
    if not isinstance(targets_imports, list):
        targets_imports = [targets_imports]
    targets_deps_issues = []
    for target_imports in targets_imports:
        target_imports_list = [(imp, "") for imp in target_imports["imports"]]
        target_imports_list.sort()

        deps_usage = {}
        for dep_exports in deps_exports:
            deps_usage.update(
                {
                    dep_exports["target"]: {
                        "used": dep_exports["alwaysused"]
                        or dep_exports["target"] == target_imports["target"]
                    }
                }
            )

        imp_i = 0
        exp_i = 0
        while imp_i < len(target_imports_list):
            imp_name = target_imports_list[imp_i][0]
            while exp_i < len(exports_to_deps) and exports_to_deps[exp_i][0] < imp_name:
                exp_i = exp_i + 1
            if exp_i >= len(exports_to_deps):
                break
            if imp_name == exports_to_deps[exp_i][0]:
                target_imports_list[imp_i] = (imp_name, exports_to_deps[exp_i][1])
                deps_usage[exports_to_deps[exp_i][1]]["used"] = True
            imp_i = imp_i + 1

        imp_matches = {}
        imp_not_found = []
        for imp_path, imp_dep in target_imports_list:
            if not imp_dep:
                imp_not_found.append(imp_path)
            else:
                imp_matches.update({imp_path: imp_dep})

        dep_unused = []
        for dep_name, dep_used in deps_usage.items():
            if not dep_used["used"]:
                dep_unused.append(dep_name)

        targets_deps_issues.append(
            {
                "target": target_imports["target"],
                "matches": imp_matches,
                "not_found": imp_not_found,
                "unused": dep_unused,
            }
        )

    with open(out_file_name, "w") as out_file:
        out_file.write(json.dumps(targets_deps_issues, sort_keys=True, indent=2))
