#include "examples/always_link/middle.h"

namespace cc_meta_examples {

// Hacky "impl" textual header inclusion.
#include "examples/always_link/middle_impl.h"

} // namespace cc_meta_examples

int wrapped_main() {
    if (cc_meta_examples::get_middle_value() != 84) {
        return 1;
    }
    if (cc_meta_examples::kMiddleValueHalf != 42) {
        return 1;
    }
    return 0;
}
