"""Some aspects for the cc_meta linting"""

load("@bazel_cc_meta//:defs.bzl", "default_cc_meta_aspect")
load("@bazel_cc_meta//cc_meta:cc_meta.bzl", "CcMetaInfo")
load("@bazel_skylib//lib:paths.bzl", "paths")
load("@rules_cc//cc:defs.bzl", "CcInfo")
load("@rules_cc//cc:find_cc_toolchain.bzl", "find_cpp_toolchain", "use_cc_toolchain")
load("@rules_python//python:defs.bzl", "py_binary")

CcClangTidyReportInfo = provider(
    "Report from clang-tidy about cc targets.",
    fields = {
        "clang_tidy_fixes": "clang_tidy_fixes.yaml file (from --export-fixes)",
    },
)

def _clang_tidy_aspect_impl(target, ctx):
    tidy_fixes = ctx.actions.declare_file(target.label.name + "_cc_meta_clang_tidy_fixes.yaml")

    if (CcMetaInfo not in target) or (CcInfo not in target) or (ctx.label.workspace_root.startswith("external")):
        # Nothing to lint
        ctx.actions.write(output = tidy_fixes, content = "")
        return [
            OutputGroupInfo(clang_tidy_fixes = [tidy_fixes]),
            CcClangTidyReportInfo(
                clang_tidy_fixes = tidy_fixes,
            ),
        ]

    # Assemble list of buildable files (srcs and hdrs)
    buildable_files = []

    if hasattr(ctx.rule.attr, "srcs"):
        for src in ctx.rule.attr.srcs:
            buildable_files.extend(src.files.to_list())

    if hasattr(ctx.rule.attr, "hdrs"):
        for src in ctx.rule.attr.hdrs:
            buildable_files.extend(src.files.to_list())

    if not buildable_files:
        # Nothing to lint
        ctx.actions.write(output = tidy_fixes, content = "")
        return [
            OutputGroupInfo(clang_tidy_fixes = [tidy_fixes]),
            CcClangTidyReportInfo(
                clang_tidy_fixes = tidy_fixes,
            ),
        ]

    cc_toolchain = find_cpp_toolchain(ctx)
    toolchain_files = cc_toolchain.all_files

    # Look up clang-tidy path
    # Find the compiler path (e.g., 'external/toolchains_llvm.../bin/clang')
    compiler_path = cc_toolchain.compiler_executable
    toolchain_tidy_path = ""

    # Check if the toolchain files contain a matching clang-tidy binary path
    for f in toolchain_files.to_list():
        if f.path.endswith("bin/clang-tidy"):
            toolchain_tidy_path = f.path
            break

    # If the toolchain files list didn't explicitly include it, construct it from the compiler path
    if not toolchain_tidy_path:
        toolchain_tidy_path = paths.join(paths.dirname(compiler_path), "clang-tidy")

    dependency_headers = target[CcInfo].compilation_context.headers

    cc_meta_info = target[CcMetaInfo]

    clang_tidy_inputs = depset(
        direct = [cc_meta_info.compile_commands_json] +
                 ([ctx.files._tidy_config_file[0]] if ctx.files._tidy_config_file else []) +
                 ctx.files._tidy_configs +
                 buildable_files,
        transitive = [toolchain_files, dependency_headers],
    )
    clang_tidy_args = ctx.actions.args()
    clang_tidy_args.add("--cmd-in", cc_meta_info.compile_commands_json)
    if ctx.files._tidy_config_file:
        clang_tidy_args.add("--tidy-config", ctx.files._tidy_config_file[0].path)
    clang_tidy_args.add("--tidy-fixes", tidy_fixes.path)
    clang_tidy_args.add("--tidy-bin", toolchain_tidy_path)
    clang_tidy_args.add_all(buildable_files)
    ctx.actions.run(
        outputs = [tidy_fixes],
        inputs = clang_tidy_inputs,
        executable = ctx.executable._run_clang_tidy_on_cmd,
        arguments = [clang_tidy_args],
        mnemonic = "ClangTidy",
        progress_message = "Running clang-tidy on %s" % target.label,
    )

    return [
        OutputGroupInfo(clang_tidy_fixes = [tidy_fixes]),
        CcClangTidyReportInfo(
            clang_tidy_fixes = tidy_fixes,
        ),
    ]

def clang_tidy_aspect_factory(
        tidy_config_file = Label("@bazel_cc_meta//cc_meta:empty_placeholder"),
        tidy_configs = [],
        cc_meta_aspect = default_cc_meta_aspect):
    """
    Create a clang-tidy aspect to gather reports about C++ sources.

    Use the factory in a `.bzl` file to instantiate an aspect:
    ```starlark
    load("@bazel_cc_meta//cc_meta:linters.bzl", "clang_tidy_aspect_factory")

    your_clang_tidy_aspect = clang_tidy_aspect_factory(<aspect_options>)
    ```

    Args:
        tidy_config_file: Location of a .clang-tidy file to use.
        tidy_configs: List of config files needed and found by clang-tidy.
        cc_meta_aspect: Aspect to run.
    """
    return aspect(
        implementation = _clang_tidy_aspect_impl,
        attr_aspects = ["deps"],
        required_providers = [CcInfo],
        required_aspect_providers = [[CcMetaInfo]],
        requires = [cc_meta_aspect],
        provides = [OutputGroupInfo, CcClangTidyReportInfo],
        fragments = ["cpp"],
        toolchains = use_cc_toolchain(),
        attrs = {
            "_run_clang_tidy_on_cmd": attr.label(
                default = Label("@bazel_cc_meta//cc_meta:run_clang_tidy_on_cmd"),
                executable = True,
                cfg = "exec",
                doc = "Injects the execroot into the compile_commands file and runs clang-tidy.",
            ),
            "_tidy_config_file": attr.label(
                default = tidy_config_file,
                doc = "Location of a .clang-tidy file to use.",
            ),
            "_tidy_configs": attr.label_list(
                default = tidy_configs,
                doc = "Location of a .clang-tidy file to use.",
            ),
        },
    )

default_clang_tidy_aspect = clang_tidy_aspect_factory()

def _expand_template_impl(ctx):
    script = ctx.actions.declare_file(ctx.attr.name)
    ctx.actions.expand_template(
        output = script,
        is_executable = True,
        template = ctx.file._script_template,
        substitutions = {
            "        {target_patterns}": "\n".join(
                ["        {},".format(repr(t)) for t in ctx.attr.targets],
            ),
            "{clang_tidy_aspect}": '"--aspects={}"'.format(ctx.attr.clang_tidy_aspect),
        },
    )
    return DefaultInfo(files = depset([script]))

_expand_template = rule(
    attrs = {
        "clang_tidy_aspect": attr.string(mandatory = True),
        "targets": attr.string_list(mandatory = True),
        "_script_template": attr.label(allow_single_file = True, default = "gather_clang_tidy_issues.py"),
    },
    implementation = _expand_template_impl,
)

def clang_tidy_issues_gatherer(
        name,
        clang_tidy_aspect = "@bazel_cc_meta//:defs.bzl%default_cc_meta_aspect",
        targets = ["@//..."],
        **kwargs):
    """Create a C++ metadata refresh rule.

    Args:
        name: name of rule
        clang_tidy_aspect: clang_tidy aspect to run on targets
        targets: list of target build patterns
        **kwargs: remaining arguments for generated py_binary rule
    """

    # Generate the core, runnable python script from refresh.py
    script_name = name + ".py"
    _expand_template(name = script_name, targets = targets, clang_tidy_aspect = clang_tidy_aspect)

    # Combine them so the wrapper calls the main script
    py_binary(name = name, srcs = [script_name], deps = ["@bazel_cc_meta//cc_meta:yaml_wrapper"], **kwargs)
