"""Target-backed signedness for stable table-pointer reads."""
import pytest

from decomprepair.signed_table_pointer_read import FAMILY, variants

HEADER = 'typedef unsigned char u8; typedef signed char s8;'
ASM = 'lb $v0, %lo(table)($at)\n'
SOURCE = '''extern char table[];
int f(int i) {
    u8 *p;
    p = table;
    return 1 + *(p + i);
}
'''


def test_target_signed_load_retypes_one_stable_pointer_read():
    result = variants(SOURCE, 'f', ASM, HEADER, ['-O1'])
    assert result == [(FAMILY, SOURCE.replace('*(p + i)', '*(s8 *)(p + i)'))]
    unsigned = variants(SOURCE.replace('u8 *p', 's8 *p'), 'f', ASM.replace('lb ', 'lbu '), HEADER)
    assert unsigned and '*(u8 *)(p + i)' in unsigned[0][1]


@pytest.mark.parametrize('source,asm,header,flags', [
    (SOURCE, ASM.replace('table', 'other'), HEADER, []),
    (SOURCE, ASM + 'lbu $v0, %lo(table)($at)\n', HEADER, []),
    (SOURCE.replace('p = table;', 'if (i) p = table;'), ASM, HEADER, []),
    (SOURCE.replace('p = table;', '{ p = table; }'), ASM, HEADER, []),
    (SOURCE.replace('p = table;', 'p = table; escape(&p);'), ASM, HEADER, []),
    (SOURCE.replace('p = table;', 'p = table; p = other;'), ASM, HEADER, []),
    (SOURCE.replace('p = table;', 'p = table; __asm__("" : "=r"(p));'), ASM, HEADER, []),
    (SOURCE.replace('p = table;', 'p = table; goto skip; skip:'), ASM, HEADER, []),
    (SOURCE.replace('p = table;', 'SAVE(p); p = table;'), ASM, HEADER + '\n#define SAVE(x) save(&(x))', []),
    (SOURCE.replace('p = table;', 'p = table; { int p; p = 0; }'), ASM, HEADER, []),
    (SOURCE, ASM, HEADER + '\n#include_next "other.h"', []),
    (SOURCE, ASM, HEADER, ['@flags.rsp']),
    (SOURCE, ASM, HEADER.replace('signed char s8', 'signed short s8'), []),
])
def test_uncertain_identity_or_pointer_flow_is_rejected(source, asm, header, flags):
    assert not variants(source, 'f', asm, header, flags)


@pytest.mark.parametrize('statement', [
    '*(p + i) = 2;',
    '(*(p + i)) = 2;',
    '(*(p + i))++;',
    'escape(&(*(p + i)));',
    'return sizeof (*(p + i));',
    'return i * (p + i);',
])
def test_only_unary_value_reads_are_retyped(statement):
    source = SOURCE.replace('return 1 + *(p + i);', statement)
    assert not variants(source, 'f', ASM, HEADER)
