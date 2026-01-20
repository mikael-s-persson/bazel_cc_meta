#include "examples/default_with_opts/middle.h"

namespace cc_meta_examples {

// Hacky "impl" textual header inclusion.
#include "examples/default_with_opts/middle_impl.h"

} // namespace cc_meta_examples

int main() {
    if (cc_meta_examples::get_middle_value() != 84) {
        return 1;
    }
    if (cc_meta_examples::kMiddleValueHalf != 42) {
        return 1;
    }
    return 0;
}
