#ifndef BAZEL_CC_META_EXAMPLES_DEFAULT_GOOD_MIDDLE_H_
#define BAZEL_CC_META_EXAMPLES_DEFAULT_GOOD_MIDDLE_H_

#include "examples/default_with_opts/lowest.h"

namespace cc_meta_examples {

constinit const int kMiddleValue = 2 * kLowestValue;

#ifdef PINEAPPLE_ON_PIZZA
#warning "You're sick, dude. Pineapple does not belong on a pizza!"
#endif

int get_middle_value();

} // namespace cc_meta_examples

#endif // BAZEL_CC_META_EXAMPLES_DEFAULT_GOOD_MIDDLE_H_
