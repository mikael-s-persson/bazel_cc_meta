"""Doxygen rule for Bazel."""

load("@bazel_cc_meta//:defs.bzl", "default_cc_meta_aspect")
load("@bazel_cc_meta//cc_meta:cc_meta.bzl", "CcMetaInfo")
load("@rules_cc//cc:defs.bzl", "CcInfo")
load("@rules_cc//cc:find_cc_toolchain.bzl", "find_cpp_toolchain", "use_cc_toolchain")

def _expand_make_variables(string, ctx, extra_sub_vars = {}):
    """Replace make variables in a string with their values.

    Args:
        string: The string to expand.
        ctx: The context object.
        extra_sub_vars: A dictionary of additional variables to replace in the string.
    """
    if "$(" in string:
        for variable, value in ctx.var.items():
            string = string.replace("$(%s)" % variable, value)
        for variable, value in extra_sub_vars.items():
            string = string.replace("$(%s)" % variable, value)
    return string

def _doxyfile_impl(ctx):
    doxyfile_out = ctx.actions.declare_file("Doxyfile.template")

    configurations = [_expand_make_variables(conf, ctx, {"OUTDIR": "{{OUTDIR}}"}) for conf in ctx.attr.configurations]

    ctx.actions.expand_template(
        template = ctx.file.doxyfile_template,
        output = doxyfile_out,
        substitutions = {
            "# {{ADDITIONAL PARAMETERS}}": "\n".join(configurations),
            "# {{DOT_PATH}}": ("DOT_PATH = %s" % ctx.executable.dot_executable.dirname) if ctx.executable.dot_executable else "",
        },
    )

    return [
        DefaultInfo(files = depset([doxyfile_out])),
    ]

_doxyfile = rule(
    doc = """Generate a Doxyfile from a template.""",
    implementation = _doxyfile_impl,
    attrs = {
        "configurations": attr.string_list(doc = "Additional configuration parameters to append to the Doxyfile. For example, to set the project name, use `PROJECT_NAME = example`."),
        "dot_executable": attr.label(
            executable = True,
            cfg = "exec",
            allow_single_file = True,
            doc = "dot executable to use. Must refer to an executable file.",
        ),
        "doxyfile_template": attr.label(
            allow_single_file = True,
            default = Label("@bazel_cc_meta//cc_meta:default_doxyfile_template"),
            doc = """Template file to use to generate the Doxyfile. You can provide your own or use the default one.
The following substitutions are available:
- `# {{DOT_PATH}}`: Indicate to doxygen the location of the `dot_executable`
- `# {{ADDITIONAL PARAMETERS}}`: Additional parameters given in the `configurations` attribute.
""",
        ),
    },
)

def _add_generic_configuration(configurations, name, value):
    if value == None:  # Do not add the configuration if the value is None
        return
    if type(value) == type(True):  # Convert the boolean to a string
        value = "YES" if value else "NO"
    if type(value) == type([]):  # Convert the list to a string, but ignore empty lists
        if len(value) == 0:
            return
        value = '"%s"' % '" "'.join(value)
    configurations.append("%s = %s" % (name.upper(), value))

def doxyfile_configurations(**kwargs):
    """
    Converts configuration parameters from starlark / python parameters to Doxyfile lines.

    The set of attributes the macro provides are the Doxygen configuration options.
    Depending on the type of the attribute, the macro will convert it to the appropriate string.

    Following starlark / python convention, the doxygen configuration options are specified
    in lower_snake_case, and converted to UPPER_SNAKE_CASE when set in the Doxyfile.

    For the complete list of Doxygen configuration options, please refer to the [Doxygen documentation](https://www.doxygen.nl/manual/config.html).

    ```bzl
    configs = doxyfile_configurations(formula_fontsize = 14, disable_index = True)
    configs == ["FORMULA_FONTSIZE = 14", "DISABLE_INDEX = YES"]
    ```

    Args:
        **kwargs: Arguments to convert to Doxyfile configuration options
    Returns:
        List of Doxyfile configuration lines to insert in a Doxyfile template
    """
    configs = []
    for k, v in kwargs.items():
        _add_generic_configuration(configs, k, v)
    return configs

def doxyfile(
        name,
        # Bazel specific attributes
        dot_executable = None,
        configurations = [],
        doxyfile_template = None,
        # Doxygen or Bazel attributes
        **kwargs):
    """
    Generates a Doxyfile template from a template and common configuration parameters.

    The Doxygen configuration options are passed to `configurations` and can be listed
    out as they will appear in the Doxyfile (e.g., "DISABLE_INDEX = YES") or created
    via the `doxyfile_configurations` macro.

    ```bzl
    doxyfile(
        name = "my_doxyfile",
        configurations = ["DISABLE_INDEX = YES"] # Specify configurations verbatim
            + doxyfile_configurations(formula_fontsize = 14), # Adds "FORMULA_FONTSIZE = 14"
    )
    ```

    The resulting target will produce a Doxyfile template containing the following
    substitutable placeholders:
    - `{{OUTDIR}}`: The output directory where the documentation will be generated.
    - `# {{INPUT}}`: List of input files for Doxygen to process.
    - `# {{OUTPUT DIRECTORY}}`: The output directory where the doxygen output will go.

    ### Make variables

    There are cases where you need access to information about the build environment, such as the output directory doxygen is writing to.
    In such cases, you can use make variables in the parameters of the macro.
    The `doxygen` rule will take care of expanding them to the appropriate values.

    By default, the following make variables are available:

    - `$(OUTDIR)`: The output directory where the documentation will be generated.
    - All the predefined variables indicated in the [Bazel documentation](https://bazel.build/reference/be/make-variables#predefined_variables).

    Args:
        name: Name for the target.
        dot_executable: Label of the doxygen executable. Make sure it is also added to the `tools` when generating doxygen docs.
        configurations: List of additional configuration parameters to insert in the Doxyfile file.
        doxyfile_template: The template file to use to generate the Doxyfile.
            The following substitutions are available:<br>
            - `# {{DOT_PATH}}`: Indicate to doxygen the location of the `dot_executable`<br>
            - `# {{ADDITIONAL PARAMETERS}}`: Additional parameters given in the `configurations` attribute.<br>
        **kwargs: Additional arguments to pass to the rule (e.g. `visibility = ["//visibility:public"], tags = ["manual"]`)
    """
    if doxyfile_template:
        kwargs["doxyfile_template"] = doxyfile_template

    _doxyfile(
        name = name,
        configurations = configurations,
        dot_executable = dot_executable,
        **kwargs
    )

CcDoxygenDocInfo = provider(
    "Propagates transitive Doxygen tags and paths",
    fields = {
        "output": "direct outputs as a struct containing {tag_file, html_dir, html_dir_short_path, xml_dir, xml_dir_short_path}",
        "transitive_tags": "depset of structs containing {tag_file, html_dir, html_dir_short_path, xml_dir, xml_dir_short_path}",
    },
)

def _doxygen_meta_aspect_impl(target, ctx):
    transitive_tags_lists = []
    for dep in ctx.rule.attr.deps:
        if CcDoxygenDocInfo in dep:
            transitive_tags_lists.append(dep[CcDoxygenDocInfo].transitive_tags)

    inherited_tags_depset = depset(transitive = transitive_tags_lists)

    if (CcMetaInfo not in target) or (CcInfo not in target) or (not ctx.attr._run_on_external and ctx.label.workspace_root.startswith("external")):
        # Nothing to generate
        return [CcDoxygenDocInfo(transitive_tags = inherited_tags_depset), OutputGroupInfo()]

    # Assemble list of buildable files (srcs and hdrs)
    buildable_files = []

    if hasattr(ctx.rule.attr, "srcs"):
        for src in ctx.rule.attr.srcs:
            for f in src.files.to_list():
                if not ctx.attr._run_on_generated and f.root.path:
                    continue
                buildable_files.append(f)

    if hasattr(ctx.rule.attr, "hdrs"):
        for src in ctx.rule.attr.hdrs:
            for f in src.files.to_list():
                if not ctx.attr._run_on_generated and f.root.path:
                    continue
                buildable_files.append(f)

    if not buildable_files:
        # Nothing to generate
        return [CcDoxygenDocInfo(transitive_tags = inherited_tags_depset), OutputGroupInfo()]

    cc_toolchain = find_cpp_toolchain(ctx)
    toolchain_files = cc_toolchain.all_files

    dependency_headers = target[CcInfo].compilation_context.headers

    cc_meta_info = target[CcMetaInfo]

    # Declare target outputs
    out_html_dir = ctx.actions.declare_directory(ctx.label.name + "_doxygen_html")
    out_xml_dir = ctx.actions.declare_directory(ctx.label.name + "_doxygen_xml")
    out_tag_file = ctx.actions.declare_file(ctx.label.name + "_doxygen.tag")
    out_clean_tag_file = ctx.actions.declare_file(ctx.label.name + "_doxygen_clean.tag")
    doxyfile = ctx.actions.declare_file(ctx.label.name + "_Doxyfile")

    # Append transitive tag linkages
    tag_inputs = []
    tag_file_lines = []
    for entry in inherited_tags_depset.to_list():
        tag_inputs.append(entry.tag_file)

        dep_short = entry.html_dir_short_path
        current_short = out_html_dir.short_path
        current_depth = len(current_short.split("/"))
        current_climb_to_root = "/".join([".."] * current_depth)
        corrected_html_path = "{}/{}".format(current_climb_to_root, dep_short)

        # Compute relative paths so generated HTML can find neighboring docs natively
        tag_file_lines.append("{}={}".format(entry.tag_file.path, corrected_html_path))

    # Create input paths to files to process
    input_paths = " ".join([f.path for f in buildable_files])
    config_paths = [f.path for f in ctx.files._doxygen_config_files]

    target_name = str(target.label)
    if target_name.startswith("@@//"):
        target_name = target_name.lstrip("@")
    elif target_name.startswith("@@"):
        target_name = target_name[1:]

    # Create target-specific Doxyfile configs
    doxy_config = [("@INCLUDE               = {}".format(f)) for f in config_paths] + [
        'PROJECT_NAME           = "{}"'.format(target_name),
        "OUTPUT_DIRECTORY       = {}".format(out_html_dir.dirname),
        "GENERATE_HTML          = YES",
        "HTML_OUTPUT            = {}".format(out_html_dir.basename),
        "GENERATE_XML           = YES",
        "XML_OUTPUT             = {}".format(out_xml_dir.basename),
        "INPUT                  = {}".format(input_paths),
        "GENERATE_TAGFILE       = {}".format(out_tag_file.path),
        "QUIET                  = YES",
    ]

    if tag_file_lines:
        doxy_config.append("TAGFILES = " + " \\\n           ".join(tag_file_lines))

    ctx.actions.write(doxyfile, "\n".join(doxy_config))

    doxygen_inputs = depset(
        direct = [doxyfile] + [cc_meta_info.compile_commands_json] +
                 ctx.files._doxygen_config_files +
                 buildable_files + tag_inputs,
        transitive = [toolchain_files, dependency_headers],
    )
    doxygen_args = ctx.actions.args()
    doxygen_args.add("--cmd-in", cc_meta_info.compile_commands_json)
    doxygen_args.add("--doxyfile", doxyfile)
    doxygen_args.add("--doxygen-bin", ctx.executable._executable)
    ctx.actions.run(
        outputs = [out_html_dir, out_xml_dir, out_tag_file],
        inputs = doxygen_inputs,
        executable = ctx.executable._run_doxygen_on_cmd,
        arguments = [doxygen_args],
        tools = [ctx.executable._executable],
        mnemonic = "TransitiveDoxygen",
        progress_message = "Running doxygen on %s" % target.label,
    )

    tag_clean_args = ctx.actions.args()
    tag_clean_args.add("--input", out_tag_file)
    tag_clean_args.add("--output", out_clean_tag_file)
    tag_clean_args.add("--group-name", target_name.replace("/", "_").replace(":", "_").replace("@", "_"))
    ctx.actions.run(
        outputs = [out_clean_tag_file],
        inputs = [out_tag_file],
        executable = ctx.executable._clean_doxygen_tag_file,
        arguments = [tag_clean_args],
        mnemonic = "CleanDoxygenTagFile",
        progress_message = "Cleaning tag-file for %s" % target.label,
    )

    current_tag_entry = struct(
        target_name = target_name,
        tag_file = out_clean_tag_file,
        html_dir = out_html_dir,
        html_dir_short_path = out_html_dir.short_path,
        xml_dir = out_xml_dir,
        xml_dir_short_path = out_xml_dir.short_path,
    )
    updated_tags_depset = depset([current_tag_entry], transitive = transitive_tags_lists)

    return [
        CcDoxygenDocInfo(output = current_tag_entry, transitive_tags = updated_tags_depset),
        OutputGroupInfo(doxygen_docs = depset([out_html_dir, out_xml_dir, out_clean_tag_file])),
    ]

def doxygen_meta_aspect_factory(
        doxygen_executable = Label("@doxygen//:executable"),
        doxygen_config_files = [],
        cc_meta_aspect = default_cc_meta_aspect,
        run_on_external = False,
        run_on_generated = False):
    """
    Create a doxygen aspect to gather documentation about C++ sources.

    Use the factory in a `.bzl` file to instantiate an aspect:
    ```starlark
    load("@bazel_cc_meta//cc_meta:doxygen.bzl", "doxygen_meta_aspect_factory")

    your_doxygen_aspect = doxygen_meta_aspect_factory(<aspect_options>)
    ```

    Args:
        doxygen_executable: Label of the doxygen executable to use.
        doxygen_config_files: List of Doxyfile config files to include (@INCLUDE) prior to target-specific Doxyfile configs.
        cc_meta_aspect: Aspect to run.
        run_on_external: Run clang-tidy on external files (default: false).
        run_on_generated: Run clang-tidy on generated files (default: false).
    """
    return aspect(
        implementation = _doxygen_meta_aspect_impl,
        attr_aspects = ["deps"],
        required_providers = [CcInfo],
        required_aspect_providers = [[CcMetaInfo]],
        requires = [cc_meta_aspect],
        provides = [OutputGroupInfo, CcDoxygenDocInfo],
        fragments = ["cpp"],
        toolchains = use_cc_toolchain(),
        attrs = {
            "_clean_doxygen_tag_file": attr.label(
                default = Label("@bazel_cc_meta//cc_meta:clean_doxygen_tag_file"),
                executable = True,
                cfg = "exec",
                doc = "Cleans the tag file to make it modular.",
            ),
            "_doxygen_config_files": attr.label_list(
                default = doxygen_config_files,
                doc = "List of Doxyfile config files to include (@INCLUDE) prior to target-specific Doxyfile configs.",
            ),
            "_executable": attr.label(
                default = doxygen_executable,
                executable = True,
                cfg = "exec",
                doc = "Doxygen executable to use.",
            ),
            "_run_doxygen_on_cmd": attr.label(
                default = Label("@bazel_cc_meta//cc_meta:run_doxygen_on_cmd"),
                executable = True,
                cfg = "exec",
                doc = "Injects the execroot into the compile_commands file and runs doxygen.",
            ),
            "_run_on_external": attr.bool(
                default = run_on_external,
                doc = "Run doxygen on external files (default: false).",
            ),
            "_run_on_generated": attr.bool(
                default = run_on_generated,
                doc = "Run doxygen on generated files (default: false).",
            ),
        },
    )

default_doxygen_aspect = doxygen_meta_aspect_factory()

def _doxygen_central_index_impl(ctx):
    # Gather documentation directories from all listed targets

    transitive_tags_lists = []
    for doc_target in ctx.attr.targets:
        if CcDoxygenDocInfo in doc_target:
            transitive_tags_lists.append(doc_target[CcDoxygenDocInfo].transitive_tags)

    inherited_tags_depset = depset(transitive = transitive_tags_lists)

    output_files = []
    index_file = ctx.actions.declare_file(ctx.label.name + "/index.html")
    output_files.append(index_file)

    links_data = []
    first_html_dir = None
    html_entries_dirs = []
    for entry in inherited_tags_depset.to_list():
        dep_short = entry.html_dir_short_path
        current_short = index_file.short_path
        current_depth = len(current_short.split("/")) - 1
        current_climb_to_root = "/".join([".."] * current_depth)
        corrected_html_path = "{}/{}".format(current_climb_to_root, dep_short)

        links_data.append((entry.target_name, corrected_html_path))
        html_entries_dirs.append(entry.html_dir)
        if not first_html_dir:
            first_html_dir = entry.html_dir
    links_data = sorted(links_data)

    if not first_html_dir:
        fail("doxygen_central_index rules require at least one target in 'targets'.")

    dox_boilerplate_files = ["doxygen.css", "doxygen.svg", "tabs.css", "navtree.css"]
    for bf in dox_boilerplate_files:
        bf_out_file = ctx.actions.declare_file(ctx.label.name + "/" + bf)
        output_files.append(bf_out_file)
        ctx.actions.run_shell(
            inputs = [first_html_dir],
            outputs = [bf_out_file],
            command = "cat {} > {}".format(first_html_dir.path + "/" + bf, bf_out_file.path),
        )

    # Generate the top-level index.html content
    html_entries = ""
    for name, dir_base in links_data:
        frame_content = """<!DOCTYPE html>
<html>
<head>
    <title>{name} - Framed</title>
    <style>
        body {{ margin: 0; padding: 0; height: 100vh; display: flex; flex-direction: column; font-family: sans-serif; overflow: hidden; }}
        .target-index-bar {{ background-color: #f4f6f9; border-bottom: 1px solid #ccc; padding: 12px 20px; flex-shrink: 0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
        .target-index-bar a {{ text-decoration: none; color: #0066cc; font-weight: bold; font-size: 14px; }}
        .target-index-bar a:hover {{ text-decoration: underline; }}
        iframe {{ width: 100%; flex-grow: 1; border: none; }}
    </style>
</head>
<body>
    <div class="target-index">
        <a href="./index.html">&larr; Back to Target Index</a>
    </div>
    <iframe src="./{dir_base}/index.html"></iframe>
</body>
</html>
""".format(name = name, dir_base = dir_base)
        frame_file = ctx.actions.declare_file(ctx.label.name + "/" + "{}_frame.html".format(name.replace("/", "_").replace(":", "_").replace("@", "_")))
        ctx.actions.write(frame_file, frame_content)
        output_files.append(frame_file)

        html_entries += """
        <tr class="memitem">
          <td class="memItemLeft">
            <span class="icondoc">
              <div class="doc-icon"></div>
            </span>&nbsp;
          </td>
          <td class="memItemRight">
            <a class="el" href="./{framed_page}">{name}</a>
          </td>
        </tr>
        """.format(name = name, framed_page = frame_file.basename)

    index_content = """<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "https://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en-US">
<head>
<meta http-equiv="Content-Type" content="text/xhtml;charset=UTF-8"/>
<title>{title}</title>
<link href="tabs.css" rel="stylesheet" type="text/css"/>
<link href="navtree.css" rel="stylesheet" type="text/css"/>
<link href="doxygen.css" rel="stylesheet" type="text/css" />
</head>
<body>
<div id="top"><!-- do not remove this div, it is closed by doxygen! -->
  <div id="titlearea">
    <table cellspacing="0" cellpadding="0">
      <tbody>
        <tr id="projectrow">
          <td id="projectalign">
            <div id="projectname">{title}</div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</div><!-- top -->
<div class="header">
  <div class="headertitle"><div class="title">Targets Reference</div></div>
</div><!--header-->
<div class="contents">
  <table class="memberdecls">
    <tbody>
      <tr class="heading"><td colspan="2"><h2 id="header-subdirs" class="groupheader"><a id="subdirs" name="subdirs"></a>Targets</h2></td></tr>
      {entries}
    </tbody>
  </table>
</div><!-- contents -->
<hr class="footer"/><address class="footer"><small>
Generated by bazel_cc_meta's doxygen rule
</small></address>
</body>
</html>
""".format(title = ctx.attr.project_title, entries = html_entries)

    ctx.actions.write(index_file, index_content)

    return [DefaultInfo(files = depset(output_files, transitive = [depset(html_entries_dirs)]))]

def doxygen_central_index_rule_factory(doxygen_aspect = default_doxygen_aspect):
    return rule(
        implementation = _doxygen_central_index_impl,
        attrs = {
            "project_title": attr.string(
                default = "Project Documentation",
                doc = "Title for the top-level project",
            ),
            "targets": attr.label_list(
                aspects = [doxygen_aspect],
                doc = "List of C++ targets to generate documentation for",
            ),
        },
    )

default_doxygen_central_index = doxygen_central_index_rule_factory()
