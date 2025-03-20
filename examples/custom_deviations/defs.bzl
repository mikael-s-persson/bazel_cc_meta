"""Bazel module to create a custom cc_meta aspect"""

load("@bazel_cc_meta//cc_meta:cc_meta.bzl", "cc_meta_aspect_factory")

custom_cc_meta_aspect = cc_meta_aspect_factory(
    deviations = [Label("@//examples/custom_deviations:custom_cc_meta_deviations")],
)
