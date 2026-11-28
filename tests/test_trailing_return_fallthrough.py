from decomprepair import registry
from decomprepair.trailing_return_fallthrough import FAMILY, variants

SOURCE = """
typedef unsigned char u8;
int check_a(u8);
int check_b(u8);

u8 evaluate(u8 state, u8 k, u8 x, u8 y, u8 f1, u8 f2, u8 f3, u8 f4) {
    u8 r1;
    u8 r2;
    if (state == 0) {
        if (k < 5) {
            r1 = check_a(x);
            r2 = check_a(y);
            if (r1 && r2) {
                if (f1) {
                    return check_a(x) ? 3 : 2;
                }
                return 3;
            }
            if (r1) {
                if (f1) {
                    return 2;
                }
                if (f2) {
                    return check_a(x) ? 2 : 0;
                }
                return 2;
            }
            return 0;
        } else if (k == 45) {
            if (check_a(x)) {
                if (y == 1) {
                    return 1;
                }
            }
        }
        return 0;
    } else if (state == 60) {
        r1 = check_a(x);
        r2 = check_b(y);
        if (r1 && r2) {
            if (f1 && f3) {
                return (f1 && r2) ? 3 : 1;
            }
            if (f1 && f4) {
                f1 = check_a(x);
                f4 = check_b(y);
                if (f1 && f4) {
                    return 3;
                }
                if (f1) {
                    return 2;
                }
                if (f4) {
                    return 1;
                }
                return 0;
            }
            if (f2 && f3) {
                f2 = check_a(x);
                f3 = check_b(y);
                if (f2 && f3) {
                    return 3;
                }
                if (f2) {
                    return 1;
                }
                if (f3) {
                    return 2;
                }
                return 0;
            }
            if (f1) {
                return check_a(x) ? 3 : 1;
            }
            return 3;
        }
        return 0;
    } else if (state == 120) {
        if (x == 0xFF || y == 0xFF) {
            return 0;
        }
        {
            if (k < 5) {
                f1 = check_a(x);
                r2 = check_a(y);
                if (f1 && r2) {
                    return 2;
                }
                return 0;
            } else if (k == 43) {
                return (check_b(x) && y == 1) ? (2) : (0);
            }
            return 0;
        }
    }
    return 0;
}
"""


def test_combines_fallthrough_rewrites_as_single_child():
    result = variants(SOURCE, 'evaluate')
    assert len(result) == 1
    family, text = result[0]
    assert family == FAMILY
    assert any(entry.module == 'trailing_return_fallthrough' for entry in registry.declared())

    # Early guard `return 0;` before further work and final `return 0;` stay intact.
    assert 'if (x == 0xFF || y == 0xFF) {\n            return 0;\n        }' in text
    assert text.rstrip().endswith('return 0;\n}')
    assert text.count('return 0;') == 2

    # Non-default ternaries (`? 3 : 2`, `? 3 : 1`) are untouched.
    assert 'return check_a(x) ? 3 : 2;' in text
    assert 'return (f1 && r2) ? 3 : 1;' in text

    # Default-0 ternaries and sequential guarded returns become else-if fallthroughs.
    assert '? 2 : 0' not in text
    assert '? (2) : (0)' not in text
    assert '} else if (f2) {\n                    if (check_a(x)) {\n                        return 2;\n                    }\n                } else {\n                    return 2;\n                }' in text
    assert '} else if (f1 && f4) {' in text
    assert '} else if (f2 && f3) {' in text
    assert 'if (check_b(x) && y == 1) {\n                    return 2;\n                }' in text

    # Idempotent once rewritten.
    assert variants(text, 'evaluate') == []


def test_does_not_churn_unrelated_sequential_returns():
    unrelated = """
int pick(int a, int b) {
    if (a > 0) {
        if (b == 1) {
            return 2;
        }
        if (b == 2) {
            return 3;
        }
        return 1;
    }
    return 0;
}
"""
    assert variants(unrelated, 'pick') == []


def test_declines_unsafe_or_macro_context():
    assert not variants(SOURCE.replace('u8 r1;', 'volatile u8 r1;'), 'evaluate')
    assert not variants(SOURCE.replace('u8 r1;', 'u8 r1;\nlabel_here:'), 'evaluate')
    assert not variants(SOURCE, 'evaluate', flags=['-Dcheck_a=other'])
    assert not variants(SOURCE, 'evaluate', header='#define check_a(v) ((v) + 1)')
    assert not variants(SOURCE, 'evaluate', header='#include "custom.h"')
