"""Some aspects for the cc_meta extraction"""

load("@bazel_skylib//lib:paths.bzl", "paths")
load("@rules_cc//cc:action_names.bzl", "CPP_COMPILE_ACTION_NAME")
load("@rules_cc//cc:find_cc_toolchain.bzl", "find_cpp_toolchain", "use_cc_toolchain")
load("@rules_cc//cc/common:cc_common.bzl", "cc_common")
load("@rules_python//python:defs.bzl", "py_binary")

CcMetaInfo = provider(
    "Metadata information about cc targets.",
    fields = {
        "compile_commands_json": "compile_command.json file",
        "deps_issues_json": "issues with target dependencies",
        "direct_exports": "include paths of public headers",
        "direct_exports_json": "include paths of public headers",
        "direct_imports_json": "direct includes json file",
    },
)

CcMetaDeviationsInfo = provider(
    "Deviations for targets to be treated differently (see make_cc_meta_deviations).",
    fields = {
        "deviations": "Dictionary with structure { target_label: json-string }",
    },
)

def _make_cc_meta_deviations_impl(ctx):
    return CcMetaDeviationsInfo(deviations = ctx.attr.deviations)

_make_cc_meta_deviations = rule(
    implementation = _make_cc_meta_deviations_impl,
    provides = [CcMetaDeviationsInfo],
    attrs = {
        "deviations": attr.label_keyed_string_dict(),
    },
)

# These deviations collect a few shadow dependencies inserted by Bazel.
_CC_META_DEFAULT_DEVIATIONS = {
    Label("@rules_cc//:link_extra_lib"): json.encode({"alwaysused": True, "skip": True}),
    Label("@rules_cc//:empty_lib"): json.encode({"alwaysused": True, "skip": True}),
}

def make_cc_meta_deviations(name, deviations = {}, **kwargs):
    """Make a set of deviations for targets to be treated differently.

    Using this rule, special-cases can be created for various reasons.
    See the "known issues" section of the README.md for examples of when it might be
    necessary to treat certain targets differently.

    The deviations are structured as a dictionary of dictionaries. The top-level
    key is the Label of target to which the deviations should be applied.
    A deviation set is dictionary that can contain a few elements (all optional):

     - "exports": a list of include paths that should be added to the set of include
                  paths that cc_meta discovered for that target. This can be used for
                  false-negatives, unusual include path specifications or deeply-wrapped
                  targets.
     - "alwaysused": a bool to signal that this target should always be considered as
                     used, even if the dependent is not including any of its headers. By
                     default, targets with the attribute "alwayslink = True" will be
                     considered used. In some cases, with wrapped targets for example,
                     it might be required to externally mark additional targets as used.
                     Adding 'alwayslink = True' to a target has the same effect.
     - "forward_exports": a bool to signal that this target should be considered as
                          exporting all of its direct dependencies' exports. Note that
                          this is not recursive, it only forwards direct exports. Applying
                          this rule recursively is fraught with issues, so that option does
                          not exist (sorry).
                          Adding "cc_meta_forward_exports" to a target's 'tags' attribute
                          has the same effect (preferred, if possible).
     - "skip": a bool to signal that this target should not be analyzed. Note, however, that
               the other deviations will still be applied. In other words, listing "exports"
               and setting "skip" to true results that target not being analyzed but having
               that specific set of exports (only). Similarly, in conjunction with
               "forward_exports", the target would have only its direct dependencies' exports.
               Adding "cc_meta_skip" to a target's 'tags' attribute has the same effect
               (preferred, if possible).

    Args:
        name: Unique name for this target.
        deviations: Dictionary containing various targets and how they should be treated.
        **kwargs: General common rule attributes (e.g., visibility).
    """
    json_deviations = {}
    for key, values in deviations.items():
        json_deviations.update({key: json.encode(values)})
    _make_cc_meta_deviations(
        name = name,
        deviations = json_deviations,
        **kwargs
    )

def _find_cc_meta_deviation(target, deviations):
    # Deviations could be a Target or Label deviation.
    if target in deviations:
        return deviations[target]
    if target.label in deviations:
        return deviations[target.label]
    return None

def _is_external(ctx):
    return ctx.label.workspace_root.startswith("external")

def _match_lists(a_list, b_list):
    # Starlark doesn't seem to have set intersections (?)
    for a in a_list:
        if a in b_list:
            return True
    return False

def _cc_meta_aspect_impl(target, ctx):
    # Declare all the outputs up-top.
    comb_incl_file = ctx.actions.declare_file(ctx.rule.attr.name + "_cc_meta_imports.json")
    comb_cmd_file = ctx.actions.declare_file(ctx.rule.attr.name + "_cc_meta_compile_commands.json")
    deps_issues_file = ctx.actions.declare_file(ctx.rule.attr.name + "_cc_meta_deps_issues.json")
    pub_hdrs_file = ctx.actions.declare_file(ctx.rule.attr.name + "_cc_meta_exports.json")

    skipped_tags = ctx.attr._skipped_tags

    # This seems to be the most universal target full-name.
    # cc_meta always refers to targets as @@repo//path:name, it only resolves them when hitting buildozer.
    target_qualified_name = "@@{}//{}:{}".format(target.label.repo_name, target.label.package, target.label.name)

    target_deviations = _find_cc_meta_deviation(target, _CC_META_DEFAULT_DEVIATIONS)
    for attr_deviations in ctx.attr._target_deviations:
        if target_deviations:
            break
        target_deviations = _find_cc_meta_deviation(target, attr_deviations[CcMetaDeviationsInfo].deviations)
    target_deviation_rules = {}
    if target_deviations:
        target_deviation_rules = json.decode(target_deviations)

    # We consider a target as always used if it is marked with 'alwayslink' attribute
    # or if a deviation exists that tells us to do so.
    target_alwaysused = False
    if hasattr(ctx.rule.attr, "alwayslink"):
        target_alwaysused = ctx.rule.attr.alwayslink
    if ("alwaysused" in target_deviation_rules) and target_deviation_rules["alwaysused"]:
        target_alwaysused = True

    # We start the list of exports with whatever deviation exports were given.
    public_header_paths = []
    if "exports" in target_deviation_rules:
        public_header_paths.extend(target_deviation_rules["exports"])

    # Add exports from direct dependencies if this target's deviation tells us to.
    hasfwdtag = (hasattr(ctx.rule.attr, "tags") and "cc_meta_forward_exports" in ctx.rule.attr.tags)
    hasfwddev = (("forward_exports" in target_deviation_rules) and target_deviation_rules["forward_exports"])
    if hasfwdtag or hasfwddev:
        for dep in ctx.rule.attr.deps:
            if not CcMetaInfo in dep:
                continue
            public_header_paths.extend(dep[CcMetaInfo].direct_exports)

    # We will skip targets that have a designated tag or deviation.
    target_should_skip = False
    hasskiptag = (hasattr(ctx.rule.attr, "tags") and _match_lists(skipped_tags, ctx.rule.attr.tags))
    hasskipdev = (("skip" in target_deviation_rules) and target_deviation_rules["skip"])
    target_should_skip = (hasskipdev or hasskiptag)

    # Assemble the list of expected public header paths used by dependents.

    # In theory, we could be faster and stricter to compute the include paths, but Bazel seems
    # to do some weird things, especially with generated files that make any reconstruction based
    # on hdrs paths and attributes like strip_include_prefix and include_prefix impossible.
    # Instead, we just brute-force to the shortest include path we could use for each header.
    # N.B.: It might make sense to add all possible partial include paths.
    # Usually, generated header paths might be:
    #  bazel-out/k8-dbg/bin/external/foo_cc_proto~/_virtual_includes/foo_proto/bar/foo.pb.h
    # Somewhere in external_includes or quote_includes, we'll find:
    #  bazel-out/k8-dbg/bin/external/foo_cc_proto~/_virtual_includes/foo_proto
    # But technically "_virtual_includes/foo_proto/bar/foo.pb.h" is also a valid (and very stupid) include path.
    for direct_hdr in target[CcInfo].compilation_context.direct_public_headers + target[CcInfo].compilation_context.direct_textual_headers:
        shortest_header_path = direct_hdr.path
        for ext_incl in target[CcInfo].compilation_context.external_includes.to_list() + target[CcInfo].compilation_context.quote_includes.to_list():
            if paths.starts_with(direct_hdr.path, ext_incl):
                potential_header_path = paths.relativize(direct_hdr.path, ext_incl)
                if len(potential_header_path) < len(shortest_header_path):
                    shortest_header_path = potential_header_path
        public_header_paths.append(shortest_header_path)

    if not ctx.rule.kind in ["cc_binary", "cc_library", "cc_test"]:
        # We don't really know if these targets can be analysed, and we cannot remove them as 'unused'.
        target_alwaysused = True
        target_should_skip = True

    # The list of exports is ready, no analysis required, write it.
    ctx.actions.write(
        output = pub_hdrs_file,
        content = json.encode_indent([{
            "alwaysused": target_alwaysused,
            "exports": public_header_paths,
            "target": target_qualified_name,
        }], indent = "  "),
    )

    # The output for a skipped target is essentially just the list of exports, the rest is empty.
    # Skipping means we should not attempt to parse any of its source files, and so, we cannot
    # create a usable compilation command, nor discover what it tries to include.
    if target_should_skip:
        ctx.actions.write(
            output = comb_incl_file,
            content = json.encode_indent([], indent = "  "),
        )
        ctx.actions.write(
            output = comb_cmd_file,
            content = json.encode_indent([], indent = "  "),
        )
        ctx.actions.write(
            output = deps_issues_file,
            content = json.encode_indent([{
                "matches": {},
                "not_found": [],
                "target": target_qualified_name,
                "unused": [],
            }], indent = "  "),
        )
        return [
            OutputGroupInfo(cc_meta = depset([comb_incl_file, comb_cmd_file, pub_hdrs_file, deps_issues_file])),
            CcMetaInfo(
                direct_imports_json = comb_incl_file,
                compile_commands_json = comb_cmd_file,
                direct_exports = public_header_paths,
                direct_exports_json = pub_hdrs_file,
                deps_issues_json = deps_issues_file,
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

    # Now, we can get serious and find the C++ toolchain
    cc_toolchain = None
    feature_configuration = None
    cc_compiler_path = None
    if buildable_files:
        cc_toolchain = find_cpp_toolchain(ctx)
        feature_configuration = cc_common.configure_features(
            ctx = ctx,
            cc_toolchain = cc_toolchain,
            requested_features = ctx.features,
            unsupported_features = ["module_maps"] + ctx.disabled_features,
        )

        cc_compiler_path = cc_common.get_tool_for_action(
            feature_configuration = feature_configuration,
            action_name = CPP_COMPILE_ACTION_NAME,
        )

    # Assemble direct include lists and compile commands for each compilable file.

    # We compile everything as C++.
    # For preprocessor, that makes no behavioral difference, except it could choke on C++-only options.
    # For the compile commands, this could be a problem for pure C targets (nowadays, C code that can't be
    # syntactically analysed as C++ is pretty rare).
    # We have to force C++, otherwise compilers deduce the language from file extensions, which is very inaccurate.
    # TODO: Figure out what the Bazel way is to distinguish C vs C++ targets (excluding brittle hacks).
    _CC_META_FORCE_CPP_ARGS = ["-x", "c++"]

    incl_files = []
    comp_cmd_list = []
    for f in buildable_files:
        if not _is_external(ctx):
            # Create a temporary file as 'source.cc.include_for_target_name' because the same
            # source could appear in multiple targets (naughty!).
            incl_file = ctx.actions.declare_file(f.basename + ".includes_for_" + target.label.name)
            incl_files.append(incl_file)

            # Invoke the preprocessor (why does Bazel make this so convoluted?)
            # We compile everything as C++, it shouldn't really matter because this is preprocessor-only.
            # TODO: Figure out what is the Bazel way to distinguish C vs C++ targets (excluding brittle hacks).
            cc_incl_compile_variables = cc_common.create_compile_variables(
                feature_configuration = feature_configuration,
                cc_toolchain = cc_toolchain,
                user_compile_flags = ctx.fragments.cpp.copts + ctx.fragments.cpp.cxxopts + ["-MM", "-MF", incl_file.path, "-E", "-MG"] + _CC_META_FORCE_CPP_ARGS,
                source_file = f.path,
                # A successful compilation would require all include paths, but:
                #  '-E' means we only preprocess.
                #  '-MG' means we don't care if we can't find headers.
                # The result is that we get a list of all includes, as they are, with preprocessed directives.
                preprocessor_defines = depset(
                    transitive = [
                        target[CcInfo].compilation_context.defines,
                        target[CcInfo].compilation_context.local_defines,
                    ],
                ),
            )
            cc_incl_command_line = cc_common.get_memory_inefficient_command_line(
                feature_configuration = feature_configuration,
                action_name = CPP_COMPILE_ACTION_NAME,
                variables = cc_incl_compile_variables,
            )
            cc_incl_env = cc_common.get_environment_variables(
                feature_configuration = feature_configuration,
                action_name = CPP_COMPILE_ACTION_NAME,
                variables = cc_incl_compile_variables,
            )
            ctx.actions.run(
                mnemonic = "CcGetDirectIncludes",
                executable = ctx.executable._run_suppress_stdout,
                arguments = [cc_compiler_path] + cc_incl_command_line,
                env = cc_incl_env,
                inputs = depset(
                    [f] + target[CcInfo].compilation_context.headers.to_list(),
                    transitive = [cc_toolchain.all_files],
                ),
                outputs = [incl_file],
            )

        # Make the actual compiler command
        cc_cmd_compile_variables = cc_common.create_compile_variables(
            feature_configuration = feature_configuration,
            cc_toolchain = cc_toolchain,
            user_compile_flags = ctx.fragments.cpp.copts + ctx.fragments.cpp.cxxopts + _CC_META_FORCE_CPP_ARGS,
            source_file = f.path,
            include_directories = target[CcInfo].compilation_context.includes,
            quote_include_directories = depset(
                transitive = [target[CcInfo].compilation_context.quote_includes, target[CcInfo].compilation_context.external_includes],
            ),
            system_include_directories = target[CcInfo].compilation_context.system_includes,
            framework_include_directories = target[CcInfo].compilation_context.framework_includes,
            preprocessor_defines = depset(
                transitive = [target[CcInfo].compilation_context.defines, target[CcInfo].compilation_context.local_defines],
            ),
        )
        cc_cmd_command_line = cc_common.get_memory_inefficient_command_line(
            feature_configuration = feature_configuration,
            action_name = CPP_COMPILE_ACTION_NAME,
            variables = cc_cmd_compile_variables,
        )
        comp_cmd_list.append({
            "arguments": cc_cmd_command_line,
            "directory": "",  # We'll have to get the workspace root later (see refresh.py script).
            "file": f.path,
        })

    # This action reads the Makefile outputs with includes for each source file into one json output file.
    ctx.actions.run(
        executable = ctx.executable._combine_includes_lists,
        arguments = [f.path for f in incl_files] + [comb_incl_file.path] + [target_qualified_name],
        inputs = depset(incl_files),
        outputs = [comb_incl_file],
    )

    # Output combined compiler commands list to json output file.
    ctx.actions.write(
        output = comb_cmd_file,
        content = json.encode_indent(comp_cmd_list, indent = "  "),
    )

    # Now, we can eagerly inspect the imports and exports to detect dependency issues.
    # We do this here because we have all the information propagated and cached by Bazel,
    # if we did this later (e.g., in a bazel run) we'd have to stupidly go through everything.

    if _is_external(ctx):
        # Pretend that external targets have no imports, no deps, no issues.
        # We can't fix them if they have issues anyways.
        ctx.actions.write(
            output = deps_issues_file,
            content = json.encode_indent([{
                "matches": {},
                "not_found": [],
                "target": target_qualified_name,
                "unused": [],
            }], indent = "  "),
        )
    elif ("forward_exports" in target_deviation_rules) and target_deviation_rules["forward_exports"]:
        # If this target forwards its exports it will find itself for all its includes,
        # so that will make all its deps appear unused, so we just remove them.
        # We should still detect 'not_found' includes, so we still need to run the checker.
        ctx.actions.run(
            executable = ctx.executable._check_direct_deps_exports,
            arguments = [pub_hdrs_file.path] + [comb_incl_file.path] + [deps_issues_file.path],
            inputs = depset([pub_hdrs_file] + [comb_incl_file]),
            outputs = [deps_issues_file],
        )
    else:
        # Check for dependency issues.
        # Gather the list of exports files from CcMetaInfo of direct dependencies.
        deps_direct_exports = []
        for dep in ctx.rule.attr.deps:
            if not CcMetaInfo in dep:
                continue
            deps_direct_exports.append(dep[CcMetaInfo].direct_exports_json)

        # Check includes against exports from target itself and its direct dependencies.
        ctx.actions.run(
            executable = ctx.executable._check_direct_deps_exports,
            arguments = [f.path for f in deps_direct_exports] + [pub_hdrs_file.path] + [comb_incl_file.path] + [deps_issues_file.path],
            inputs = depset(deps_direct_exports + [pub_hdrs_file] + [comb_incl_file]),
            outputs = [deps_issues_file],
        )

    return [
        OutputGroupInfo(cc_meta = depset([comb_incl_file, comb_cmd_file, pub_hdrs_file, deps_issues_file])),
        CcMetaInfo(
            direct_imports_json = comb_incl_file,
            compile_commands_json = comb_cmd_file,
            direct_exports = public_header_paths,
            direct_exports_json = pub_hdrs_file,
            deps_issues_json = deps_issues_file,
        ),
    ]

_CC_META_DEFAULT_SKIPPED_TAGS = ["cc_meta_skip"]

def cc_meta_aspect_factory(
        deviations = [],
        skipped_tags = []):
    """
    Create a C++ metadata aspect to gather information about C++ sources.

    Use the factory in a `.bzl` file to instantiate an aspect:
    ```starlark
    load("@bazel_cc_meta//cc_meta:cc_meta.bzl", "cc_meta_aspect_factory")

    your_cc_meta_aspect = cc_meta_aspect_factory(<aspect_options>)
    ```

    Args:
        deviations: List of targets created by make_cc_meta_deviations.
        skipped_tags: List of string tags to skip.
    """
    return aspect(
        implementation = _cc_meta_aspect_impl,
        attr_aspects = ["deps"],
        required_providers = [CcInfo],
        provides = [OutputGroupInfo, CcMetaInfo],
        fragments = ["cpp"],
        toolchains = use_cc_toolchain(),
        attrs = {
            "_check_direct_deps_exports": attr.label(
                default = Label("@bazel_cc_meta//cc_meta:check_direct_deps_exports"),
                executable = True,
                cfg = "exec",
                doc = "Tool for checking target imports against deps exports.",
            ),
            "_combine_includes_lists": attr.label(
                default = Label("@bazel_cc_meta//cc_meta:combine_includes_lists"),
                executable = True,
                cfg = "exec",
                doc = "Tool for combining includes dumps.",
            ),
            "_run_suppress_stdout": attr.label(
                default = Label("@bazel_cc_meta//cc_meta:run_suppress_stdout"),
                executable = True,
                cfg = "exec",
                doc = "Run a command with stdout to /dev/null.",
            ),
            "_skipped_tags": attr.string_list(
                default = skipped_tags + _CC_META_DEFAULT_SKIPPED_TAGS,
                doc = "Tags to identify targets to be skipped.",
            ),
            "_target_deviations": attr.label_list(
                default = deviations,
                providers = [CcMetaDeviationsInfo],
            ),
        },
    )

def _expand_template_impl(ctx):
    script = ctx.actions.declare_file(ctx.attr.name)
    ctx.actions.expand_template(
        output = script,
        is_executable = True,
        template = ctx.file._script_template,
        substitutions = {
            "        {target_patterns}": "\n".join(["        {},".format(repr(t)) for t in ctx.attr.targets]),
            "{cc_meta_aspect}": "\"--aspects={}\"".format(ctx.attr.cc_meta_aspect),
        },
    )
    return DefaultInfo(files = depset([script]))

_expand_template = rule(
    attrs = {
        "cc_meta_aspect": attr.string(mandatory = True),
        "targets": attr.string_list(mandatory = True),
        "_script_template": attr.label(allow_single_file = True, default = "refresh.py"),
    },
    implementation = _expand_template_impl,
)

def refresh_cc_meta(
        name,
        cc_meta_aspect = "@bazel_cc_meta//:defs.bzl%default_cc_meta_aspect",
        targets = ["@//..."],
        **kwargs):
    """Create a C++ metadata refresh rule.

    Args:
        name: name of rule
        cc_meta_aspect: cc_meta aspect to run on targets
        targets: list of target build patterns
        **kwargs: remaining arguments for generated py_binary rule
    """

    # Generate the core, runnable python script from refresh.py
    script_name = name + ".py"
    _expand_template(name = script_name, targets = targets, cc_meta_aspect = cc_meta_aspect)

    # Combine them so the wrapper calls the main script
    py_binary(
        name = name,
        srcs = [script_name],
        **kwargs
    )
