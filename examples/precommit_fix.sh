#!/bin/bash

# This is an example pre-commit script (e.g., for .pre-commit-config.yaml).
# Due to the ways in which one might want to customize the invocations below,
# we can't really provide a one-size-fits-all script.

# First refresh the databases.
bazel run //examples/default_good:refresh
# Then, run the fix_deps script with files provided by pre-commit hook.
bazel run @bazel_cc_meta//cc_meta:fix_deps -- -n "$@"
