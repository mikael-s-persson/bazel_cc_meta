#ifndef BAZEL_CC_META_EXAMPLES_DEFAULT_TRANSITIVE_MIDDLE_H_
#define BAZEL_CC_META_EXAMPLES_DEFAULT_TRANSITIVE_MIDDLE_H_

#include "examples/default_transitive/lowest.h"

namespace cc_meta_examples {

constexpr int kMiddleValue = 2 * kLowestValue;

int get_middle_value();

} // namespace cc_meta_examples

#endif // BAZEL_CC_META_EXAMPLES_DEFAULT_TRANSITIVE_MIDDLE_H_
