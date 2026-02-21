import argparse
import json
import sys


def read_json_file(file_name):
    with open(file_name, "r") as file:
        return json.load(file)


def _add_or_fuse_with_set(key, new_set, all_sets):
    if key not in all_sets:
        all_sets.update({key: new_set})
    else:
        all_sets.update({key: all_sets[key] | new_set})


def _find_import_dep_mark_used(imports_list, exports_to_deps, deps_usage, imp_i, exp_i):
    imp_name = imports_list[imp_i][0]
    while exp_i < len(exports_to_deps) and exports_to_deps[exp_i][0] < imp_name:
        exp_i = exp_i + 1
    if exp_i < len(exports_to_deps) and imp_name == exports_to_deps[exp_i][0]:
        imports_list[imp_i] = (imp_name, exports_to_deps[exp_i][1])
        deps_usage[exports_to_deps[exp_i][1]]["used"] = True
    imp_i = imp_i + 1
    return imp_i, exp_i


def main():
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
    # Fuse by target
    targets_imports_by_target = {}
    targets_ambiguous_imports_by_target = {}
    for target_imports in targets_imports:
        _add_or_fuse_with_set(
            target_imports["target"],
            set([(imp, "") for imp in target_imports["imports"]]),
            targets_imports_by_target,
        )
        if "ambiguous_imports" in target_imports:
            _add_or_fuse_with_set(
                target_imports["target"],
                set([(imp, "") for imp in target_imports["ambiguous_imports"]]),
                targets_ambiguous_imports_by_target,
            )

    targets_deps_issues = []
    for target_name, target_imports_set in targets_imports_by_target.items():
        target_imports_list = sorted(target_imports_set)
        target_ambiguous_imports_list = []
        if target_name in targets_ambiguous_imports_by_target:
            target_ambiguous_imports_list = sorted(
                targets_ambiguous_imports_by_target[target_name]
            )

        deps_usage = {}
        for dep_exports in deps_exports:
            deps_usage.update(
                {
                    dep_exports["target"]: {
                        "used": dep_exports["alwaysused"]
                        or dep_exports["target"] == target_name
                    }
                }
            )

        imp_i = 0
        amb_i = 0
        exp_i = 0
        while (
            imp_i < len(target_imports_list)
            or amb_i < len(target_ambiguous_imports_list)
        ) and exp_i < len(exports_to_deps):
            if amb_i < len(target_ambiguous_imports_list) and (
                imp_i >= len(target_imports_list)
                or target_ambiguous_imports_list[amb_i][0]
                <= target_imports_list[imp_i][0]
            ):
                if (
                    imp_i < len(target_imports_list)
                    and target_ambiguous_imports_list[amb_i][0]
                    == target_imports_list[imp_i][0]
                ):
                    amb_i = amb_i + 1
                    continue
                amb_i, exp_i = _find_import_dep_mark_used(
                    target_ambiguous_imports_list,
                    exports_to_deps,
                    deps_usage,
                    amb_i,
                    exp_i,
                )
            else:
                imp_i, exp_i = _find_import_dep_mark_used(
                    target_imports_list, exports_to_deps, deps_usage, imp_i, exp_i
                )

        # We require all non-ambiguous direct dep-imports to come from a dependency's exports.
        imp_matches = {}
        imp_not_found = []
        for imp_path, imp_dep in target_imports_list:
            if not imp_dep:
                imp_not_found.append(imp_path)
            else:
                imp_matches.update({imp_path: imp_dep})
        # We only record matches for ambiguous imports, but ignore unmatched imports (they could be transitive).
        ambiguous = []
        for imp_path, imp_dep in target_ambiguous_imports_list:
            if not imp_dep:
                ambiguous.append(imp_path)
            else:
                imp_matches.update({imp_path: imp_dep})

        dep_unused = []
        for dep_name, dep_used in deps_usage.items():
            if not dep_used["used"]:
                dep_unused.append(dep_name)

        targets_deps_issues.append(
            {
                "target": target_name,
                "matches": imp_matches,
                "not_found": imp_not_found,
                "unused": dep_unused,
                "ambiguous": ambiguous,
            }
        )

    with open(out_file_name, "w") as out_file:
        json.dump(targets_deps_issues, out_file, sort_keys=True, indent=2)


if __name__ == "__main__":
    main()
