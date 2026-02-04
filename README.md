# Bazel C/C++ Metadata Analyzer (bazel_cc_meta)

Bazel tools to analyze C/C++ metadata and target dependencies.

The objective of this library is to enable Bazel projects to generate helpful metadata around
the C/C++ targets and their dependencies. Core capabilities include:

 - Generate a `compile_commands.json` file for all C/C++ sources involved in a project's builds.
   - The `compile_commands.json` captures compilation commands and enables use of `clangd` (LSP) and other clang-based tools.
 - Gather a mapping of targets to "exports", aka includable headers, such that missing direct dependencies can be automatically found.
 - Analyze direct dependencies of targets compared to included headers to add missing ones or remove unused ones.


# Getting started

## Get a release

Choose a release from the [release page](https://github.com/mikael-s-persson/bazel_cc_meta/releases) and follow the instructions.

## Get a specific commit

### MODULE.bazel (recommended)

Importing into a Bazel module is done as usual. Some examples are given below.

#### Release version as `http_archive`

Put the following into your MODULE.bazel file (filling in version numbers and SHA)

```python
http_archive = use_repo_rule("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

bazel_dep(name = "bazel_skylib", version = "<insert appropriate version number>")
bazel_dep(name = "rules_python", version = "<insert appropriate version number>")
bazel_dep(name = "rules_cc", version = "<insert appropriate version number>")
bazel_dep(name = "rules_shell", version = "<insert appropriate version number>")
bazel_dep(name = "buildozer", version = "<insert appropriate version number>")

http_archive(
    name = "bazel_cc_meta",
    integrity = "<insert sha integrity check>",
    strip_prefix = "bazel_cc_meta-X.Y.Z",
    urls = ["https://github.com/mikael-s-persson/bazel_cc_meta/archive/refs/tags/vX.Y.Z.tar.gz"],
)
```

#### Git commit as `git_override`

Put the following into your MODULE.bazel file

```python
bazel_dep(name = "bazel_cc_meta", version = "0.0.0")
git_override(
    module_name = "bazel_cc_meta",
    commit = <commit_you_are_interested_in>,
    remote = "https://github.com/mikael-s-persson/bazel_cc_meta",
)
```

### WORKSPACE (legacy) (untested)

Put the following into your WORKSPACE file to use a specific commit

```python
load("@bazel_tools//tools/build_defs/repo:git.bzl", "git_repository")

git_repository(
    name = "bazel_cc_meta",
    commit = <commit_you_are_interested_in>,
    remote = "https://github.com/mikael-s-persson/bazel_cc_meta",
)
```

# Usage

## Default aspect

The most basic usage of `bazel_cc_meta` is to use the default configurations (aspect).

 - Default aspect: `@bazel_cc_meta//:defs.bzl%default_cc_meta_aspect`
 - Default refresh "all" tool: `@bazel_cc_meta//cc_meta:refresh_all`
 - Fix dependency tool: `@bazel_cc_meta//cc_meta:fix_deps`

If default tools (aspect or refresh tool) are not appropriate (see "Known issues"), custom
configurations can be created, see sections below.

To use the default tools, use `bazel run` to invoke the refresh tool:

```bash
bazel run [build_options] @bazel_cc_meta//cc_meta:refresh_all -- [build_options]
```

Where `build_options` should be the build configuration options you need when building your
targets, e.g., `-c opt --config=clang`. The trailing `build_options` are the options that
the script will use when invoking `bazel` under-the-hood, so those are the options that truly
determine what gets analyzed (technically, the first set is just the option for running the
script). So, in short, they should usually match and match how you build your project.

The refresh script runs the "aspect" on the build graph spawning from `//...` and generates
three files:

 - `compile_commands.json`: Compilation commands for all your sources (and "external"
   sources) and enables use of `clangd` (LSP) and other clang-based tools.
 - `target_exports.json`: Maps all discoverable targets to their set of "exports", aka
   public headers (incl. textual headers).
 - `dependency_issues.json`: Summary of dependency issues found in your targets, such
   as missing dependencies (aka "not_found" headers) and unused ones.

Running the aspect on your build graph does not require your code's actual build artifacts
and will only run on targets whose aspect output are not up-to-date. Thus, it's
usually quick after the first run.

To automatically fix the issues listed in `dependency_issues.json`, run the `fix_deps` tool:

```bash
bazel run [build_options] @bazel_cc_meta//cc_meta:fix_deps
```

The `build_options` don't really matter here, as `fix_deps` does not build anything and it's
just a vanilla python script. Under-the-hood, it uses `buildozer` to fix issues with build
rules, and it is therefore subject to its shortcomings (see Known issues).

This is pretty much it. But, given how creative C++ programmers are at creating convoluted
build rules that defeat any sane analysis tool, there is a good chance that customizations
will be needed to work around those issues (see Known issues for known examples).

## Tags

Certain tags can by used in the `tags` attribute of targets to tell `bazel_cc_meta` to
treat certain targets differently.

 - `alwayslink = True` attribute will cause the target to be considered as always used
   if it is being depended upon, so it won't be removed by the fixer, since that is
   generally appropriate for such targets.
 - `tags = ["cc_meta_skip"]` this tag causes the target to be skipped by `bazel_cc_meta`
   aspects. Outputs will still be produced for basic information, but crucially, the
   compilation commands or preprocessing will not be attempted.
 - `tags = ["cc_meta_forward_exports"]` this tag causes the exports of this target's direct
   dependencies to be forward or attributed to this target. Note that this is not recursive.

If you need some of the above behaviors to apply to targets not under your control, you
will have to create a custom deviations set (see following sections). But if you can,
using these tags is preferred as more scalable and performant.

## Custom aspects

The mechanics of this tool rely on three components:

 - A [Bazel Aspect](https://bazel.build/extending/aspects) that analyzes the targets. An
   aspect is like a shadow build graph that can be "tacked on" to build rules.
 - A refresh script that primarily runs a given aspect on a given set of target patterns,
   like `//...:all`.
 - A set of deviations (and skipped tags) that configure the aspect to treat certain targets
   differently.

Effectively, in order to customize either the target patterns or the deviations, you need
to instantiate your own custom trio of components. Doing so requires a `BUILD` and a `.bzl`
file (don't ask why). The deviations and refresh script will be rules in your `BUILD` file.
The aspect, parametrized by your custom deviations, will be created in your `.bzl` file.

In a BUILD file (e.g., //my:BUILD):

```python
load("@bazel_cc_meta//cc_meta:cc_meta.bzl", "make_cc_meta_deviations", "refresh_cc_meta")

make_cc_meta_deviations(
    name = "my_cc_meta_deviations",
    deviations = {
        # gtest and gtest_main export the gtest headers and should always be linked in (for main).
        "@com_google_googletest//:gtest": {"exports": [
            "gtest/gtest.h",
            "gmock/gmock.h",
        ]},
        "@com_google_googletest//:gtest_main": {
            "alwaysused": True,
            "forward_exports": True,
        },
    },
    visibility = ["//visibility:public"],
)

refresh_cc_meta(
    name = "refresh_foo_cc_meta",
    cc_meta_aspect = "//my:defs.bzl%my_cc_meta_aspect",   # Default: "@bazel_cc_meta//:defs.bzl%default_cc_meta_aspect"
    targets = ["//my:foo"],                               # Default: "//..." (aka "all")
    visibility = ["//visibility:public"],
)
```

In a bzl file (e.g., //my:defs.bzl):

```python
load("@bazel_cc_meta//cc_meta:cc_meta.bzl", "cc_meta_aspect_factory")

my_cc_meta_aspect = cc_meta_aspect_factory(
    deviations = [Label("@//my:my_cc_meta_deviations")],  # Default: []
    skipped_tags = ["hacky_target"],                      # Default: [] ("cc_meta_skip" always applies though)
)
```

Note that multiple deviations rules can be given to the aspect, so that they can be logically
separated. The following section digs into how those deviations are specified.

Running your own custom aspect simply involve replacing `@bazel_cc_meta//cc_meta:refresh_all` with your
custom refresh tool, e.g., `//my:refresh_foo_cc_meta` in the example above. The `fix_deps` tool does not
need to change.

## Custom deviations

The deviations are structured as a dictionary of dictionaries. The top-level
key is the `Label` or `Target` to which the deviations should be applied.
A deviation set is dictionary that can contain a few elements (all optional):

 - "exports": a list of include paths (as they would appear in dependent code)
   that should be added to the set of include paths discovered for that target.
   This can be used for false-negatives, unusual include path specifications or
   deeply-wrapped targets.
 - "alwaysused": a bool to signal that this target should always be considered as
   used, even if the dependent is not including any of its headers. By default,
   targets with the attribute "alwayslink = True" will be considered used. In
   some cases, with wrapped targets for example, it might be required to externally
   mark additional targets as used. Adding 'alwayslink = True' to a target has the
   same effect.
 - "forward_exports": a bool to signal that this target should be considered as
   exporting all of its direct dependencies' exports. Note that this is not
   recursive, it only forwards direct exports. Applying this rule recursively is
   fraught with problems, so that option does not exist (sorry). Adding
   "cc_meta_forward_exports" to a target's 'tags' attribute has the same
   effect (preferred, if possible).
 - "skip": a bool to signal that this target should not be analyzed. Note, however, that
   the other deviations will still be applied. In other words, listing "exports"
   and setting "skip" to true results that target not being analyzed but having
   that specific set of exports (only). Similarly, in conjunction with "forward_exports",
   the target would have only its direct dependencies' exports. Adding "cc_meta_skip" to
   a target's 'tags' attribute has the same effect (preferred, if possible).

## Selecting deviations

Deviations can be "selected" (in the Bazel `select` sense) through the aspect
specified in the "refresh" rule. This is, unfortunately, a bit verbose.
Here is a basic example of a selectable set of deviations.

In a BUILD file (e.g., //my:BUILD):

```python
load("@bazel_cc_meta//cc_meta:cc_meta.bzl", "make_cc_meta_deviations", "refresh_cc_meta")

make_cc_meta_deviations(
    name = "my_cc_meta_deviations",
    deviations = {
        # ... General deviations.
    },
    visibility = ["//visibility:public"],
)

make_cc_meta_deviations(
    name = "my_cc_meta_deviations_linux_only",
    deviations = {
        # ... Linux-only additional deviations.
    },
    # Restrict the deviations to Linux if the labels in the dictionary only exist in Linux.
    target_compatible_with = select({
        "@platforms//os:linux": [],
        "//conditions:default": ["@platforms//:incompatible"],
    }),
    visibility = ["//visibility:public"],
)

refresh_cc_meta(
    name = "refresh_foo_cc_meta",
    # Select the aspect based on the platform.
    cc_meta_aspect = select({
        "@platforms//os:linux": "//my:defs.bzl%my_cc_meta_aspect_for_linux",
        "//conditions:default": "//my:defs.bzl%my_cc_meta_aspect",
    }),
    visibility = ["//visibility:public"],
)
```

In a bzl file (e.g., //my:defs.bzl):

```python
load("@bazel_cc_meta//cc_meta:cc_meta.bzl", "cc_meta_aspect_factory")

my_cc_meta_aspect = cc_meta_aspect_factory(
    deviations = [Label("@//my:my_cc_meta_deviations")],
)

# Create an aspect for Linux that include both general and Linux-only deviations.
my_cc_meta_aspect_for_linux = cc_meta_aspect_factory(
    deviations = [Label("@//my:my_cc_meta_deviations"), Label("@//my:my_cc_meta_deviations_linux_only")],
)
```

# Known issues

## Approximate target queries

The `refresh` tool must use Bazel's `cquery` command to obtain a full list of dependencies spawning from the
given target pattern (e.g., `//...:all`) and attempts to do so using the `cquery`
(aka [Configurable Query](https://bazel.build/query/cquery)) in order to respect the build configuration
(e.g., `--config=`, `-c dbg`, etc.). This facility is approximate and could result in missing some targets.
If you suspect that is the case (if using a particularly difficult configuration, such as for cross-compilation),
then you can check what `bazel cquery //...:all` produces and if it lacks certain desired target, create
your own custom 'refresh' rule (see previous section) with a more fine-grained target pattern.

## Common problematic libraries

Some common libraries use convoluted target topologies (and unsurprisingly, all of them come from Google).
Here are some suggested deviations to use to resolve some issues with common libraries:

```python
make_cc_meta_deviations(
    name = "suggested_cc_meta_info_mappings",
    deviations = {
        # gtest and gtest_main export the gtest headers and should always be linked in (for main).
        "@com_google_googletest//:gtest": {"exports": [
            "gtest/gtest.h",
            "gmock/gmock.h",
        ]},
        "@com_google_googletest//:gtest_main": {
            "alwaysused": True,
            "forward_exports": True,
        },

        # benchmark and benchmark_main export the benchmark headers and should always be linked in (for main).
        "@com_google_benchmark//:benchmark": {"exports": [
            "benchmark/benchmark.h",
        ]},
        "@com_google_benchmark//:benchmark_main": {
            "alwaysused": True,
            "forward_exports": True,
        },

        # protobuf's public target effectively re-exports its dependencies' headers.
        "@com_google_protobuf//:protobuf": {"forward_exports": True},
    },
)
```

## Fixing generated targets will fail

This is a basic limitation of trying to use `buildozer` to add or remove dependencies in generated targets.
Fixes to generated targets have to be done manually because `buildozer` cannot know where those targets
actually come from or where it's appropriate to change the dependencies.

## Canonical public targets

Again, when packages declare aliases and wrapper targets, it causes problems. In particular, when trying
to add missing dependencies such targets will generally resolve to some underlying private target that is
not meant or allowed to be depended upon. It's not possible to reassign such targets back to the intended
public alias. In these cases, there will be errors trying to add those dependencies and might require
manual fixing.

Adding a deviation on the alias target can help, especially "alwaysused" and "forward_exports".

## Preprocessor logic

To discover include statements, this tool invokes the compiler in a preprocessor-only mode (`-E`) and
asks for very shallow include expansion to efficiently discover only the top-level includes. This means
that it can, to a degree, resolve preprocessor-based conditional includes and such, but it is limited
and could fail on sources that use tricky preprocessor logic to decide what headers to include.
Problems could be:

 - Discovering the wrong includes.
 - Failing to preprocess the sources if deeply buried macros are required to resolve top-level includes.

These problems can generally be solved by either skipping those targets or by wrapping the problematic
inclusion patterns in a more limited (and skipped) target. Those sorts of complicated preprocessor-based
inclusion logic should be limited and insulated for good practice anyways, so this limitation is almost
a feature rather than a bug.

## Textual headers

Bazel's `cc_*` targets (in particular, `cc_library`) distinguish between `hdrs` and `textual_hdrs` by the
key difference that `textual_hdrs` are files that can be (and are publicly) includable by dependent, like
regular headers, but are not parsable (compilable) on their own. Commonly, these are header-like files
that some libraries have which require some special inclusion pattern, such as `#`defining some things
first or including the file within some class declaration. Again, this is very bad practice and heavily
discouraged (as are preprocessor-based include logic). Bazel provides `textual_hdrs` for this purpose,
and otherwise assumes all `hdrs` can be compiled or parsed on their own (e.g., for pre-compiled headers
or C++ modules).

This tool makes the same assumption. If you have code that does not follow that rule for all targets (which
probably "just works" unless you use modules or layering checks), **fix** or skip those targets.

In order to discover includes, this tool attempts to parse all files in `hdrs` and `srcs`, which means
that includes within `textual_hdrs` **are not discoverable**.


# Disclaimer

This package is highly experimental. Keep your expectations low in terms of supported platforms or
target topologies. The weirder the setup, like using lots of "wrapper" targets, aliases or generated targets,
the less likely it is to work.

The primary platform targeted (where it is actually used) is Linux with reasonably recent Bazel and Python
versions (guessing, at least Python > 3.8, and Bazel > 7.0).

# Contributing

Contribute through the typical github mechanisms:

 - Report issues
  - Before reporting an issue, keep in mind that LSPs / editors can be finicky and sometimes require
    restarting the editor or clangd server to properly refresh its cache.
 - Create pull requests

# License

Copyright 2025-present, Mikael Persson.
This project licensed under the Apache 2.0 license.

# Credits

This tool was inspired by, and is effectively a combination of, the following tools:

 - [Depend-on-what-you-use (DWYU)](https://github.com/martis42/depend_on_what_you_use)
 - [Hedron's Compile Commands Extractor](https://github.com/hedronvision/bazel-compile-commands-extractor)

The gist of this new tool is to use the best of both worlds. DWYU employs Bazel's aspects to create
a shadow build graph over the existing build graph to extract information about imports and exports
of `cc_*` targets in order to find and fix issues with dependencies. However, the implementation is
unfortunately quite slow and limited, and `bazel_cc_meta` greatly improves the performance and adds
the mapping of target to exports which allows for not just finding missing dependencies but also fixing
them. Then, Hedron's generator of the `compile_commands.json` is based entirely on Bazel's query
features (`query`, `cquery` and `aquery`) to extract the compilation commands for each source file.
That has a number of problems, such as being approximate (Bazel's query system cannot always accurately
reflect the actual build graph), very slow (invoking Bazel on each target), and cannot effectively employ
Bazel's caching system to avoid repeated analysis of up-to-date targets. Gathering the compiler commands
through an aspect is a far superior mechanism that solves all these shortcomings.
