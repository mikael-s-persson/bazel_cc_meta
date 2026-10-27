"""Example of doxygen aspect factory"""

load("@bazel_cc_meta//cc_meta:doxygen.bzl", "doxygen_central_index_rule_factory", "doxygen_meta_aspect_factory")

good_doxygen_aspect = doxygen_meta_aspect_factory(
    doxygen_config_files = ["//examples/default_good:good_doxyfile"],
)

good_doxygen_central_index = doxygen_central_index_rule_factory(doxygen_aspect = good_doxygen_aspect)
