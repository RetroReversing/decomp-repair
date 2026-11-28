from decomprepair import registry
from decomprepair.goto_load_increment_copy import variants

SOURCE = '''
typedef signed int s32;
void f(void) {
    s32 *src;
    s32 *dst;
    s32 value;
    s32 temporary;
    temporary = *src + 1;
    dst = src;
    value = temporary;
    goto store;
store:
    *dst = value;
}
'''


def test_moves_the_addition_across_the_pointer_copy():
    result = variants(SOURCE, 'f')
    assert len(result) == 2
    text = result[0][1]
    assert 'value = *src;\n    dst = src;\n    value += 1;' in text
    assert 'temporary' not in text
    assert 'temporary = *src;\n    dst = src;\n    value = temporary;\n    value += 1;' in result[1][1]
    assert any(entry.module.endswith('goto_load_increment_copy') for entry in registry.declared())


def test_declines_escape_shadow_and_observable_temporary():
    cases = (
        SOURCE.replace('    *dst = value;', '    use(temporary);\n    *dst = value;'),
        SOURCE.replace('    *dst = value;', '    use(&value);\n    *dst = value;'),
        SOURCE.replace('    *dst = value;', '    use(&dst);\n    *dst = value;'),
        SOURCE.replace('    s32 temporary;', '    s32 temporary;\n    { int *temporary; use(temporary); }'),
        SOURCE.replace('    temporary =', '    { __typeof__(*src) value = 0; use(value); }\n    temporary ='),
        SOURCE.replace('    temporary =', '    if (value)\n    temporary ='),
        SOURCE + '\nint line = __LINE__;\n',
    )
    for source in cases:
        assert variants(source, 'f') == []
    assert variants(SOURCE, 'f', header='#include "unknown.h"') == []
    assert variants(SOURCE, 'f', flags=['-DFOO=1']) == []
