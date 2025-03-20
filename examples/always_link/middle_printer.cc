
#include <cstdio>

#include "examples/always_link/middle.h"

namespace cc_meta_examples {

// Hacky "impl" textual header inclusion.
#include "examples/always_link/middle_impl.h"

} // namespace cc_meta_examples

int wrapped_main() {
    printf("Middle value is %d, and half is %d\n", cc_meta_examples::get_middle_value(), cc_meta_examples::kMiddleValueHalf);
    return 0;
}
