#include "examples/default_good/middle.h"

namespace cc_meta_examples {

// Hacky "impl" textual header inclusion.
#include "examples/default_good/middle_impl.h"

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
