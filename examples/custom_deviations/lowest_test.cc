#include "examples/custom_deviations/lowest.h"

int wrapped_main() {
    if (cc_meta_examples::kLowestValue != 42) {
        return 1;
    }
    return 0;
}
