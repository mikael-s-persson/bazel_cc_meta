"""Some common rules for the roci repository"""

load("//cc_meta:cc_meta.bzl", "cc_meta_aspect_factory")

# Default cc_meta aspect.
# For custom deviations or skipped tags, create your own aspect:
#
# In a BUILD file (e.g., //my:BUILD):
#
# load("@bazel_cc_meta//cc_meta:cc_meta.bzl", "make_cc_meta_deviations", "refresh_cc_meta")
#
# make_cc_meta_deviations(
#     name = "my_cc_meta_deviations",
#     deviations = {
#         # gtest and gtest_main export the gtest headers and should always be linked in (for main).
#         "@com_google_googletest//:gtest": {"exports": [
#             "gtest/gtest.h",
#             "gmock/gmock.h",
#         ]},
#         "@com_google_googletest//:gtest_main": {
#             "alwaysused": True,
#             "forward_exports": True,
#         },
#     },
#     visibility = ["//visibility:public"],
# )
#
# refresh_cc_meta(
#     name = "refresh_cc_meta_all",
#     cc_meta_aspect = "//my:defs.bzl%my_cc_meta_aspect",
#     visibility = ["//visibility:public"],
# )
#
# In a bzl file (e.g., //my:defs.bzl):
#
# load("@bazel_cc_meta//cc_meta:cc_meta.bzl", "cc_meta_aspect_factory")
#
# my_cc_meta_aspect = cc_meta_aspect_factory(
#     deviations = [Label("@//my:my_cc_meta_deviations")],
#     skipped_tags = ["hacky_target"],
# )
#
default_cc_meta_aspect = cc_meta_aspect_factory()
