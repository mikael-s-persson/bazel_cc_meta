"""Providing build rules for pyyaml"""

load("@rules_python//python:defs.bzl", "py_library")

py_library(
    name = "yaml",
    srcs = glob(["yaml/**/*.py"]),
    visibility = ["//visibility:public"],
    imports = ["./yaml"],  # Puts dir directly onto the PYTHONPATH
)
