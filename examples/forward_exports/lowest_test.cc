#include "examples/forward_exports/lowest.h"

int main() {
    if (cc_meta_examples::kLowestValue != 42) {
        return 1;
    }
    return 0;
}
