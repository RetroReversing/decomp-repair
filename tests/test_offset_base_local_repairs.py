"""A pointer moved back by a constant, held in a local before the sum it is part of."""
from decomprepair import offset_base_local_repairs as o

SOURCE = '''void f(void *arg0) {
    u8 *base;
    s32 i;

    base = &D;
    i = (*base) * 0x18;
    M2C_FIELD(arg0, void **, -0x18) = (void *) (i + (base - 0x115));
    g(base);
}
'''


def test_the_offset_base_first():
    # An N64 function at 99.9% (gcc 2.7.2 reassociated the sum): exact so.
    (family, out), = o.variants(SOURCE, 'f')
    assert family == 'offset_base_local'
    assert '    u8 *base;\n    u8 *__repair_offset;' in out
    assert ('    __repair_offset = base - 0x115;\n'
            '    M2C_FIELD(arg0, void **, -0x18) = (void *) (i + __repair_offset);\n') in out


def test_the_other_order_too():
    (_, out), = o.variants(SOURCE.replace('(i + (base - 0x115))', '((base - 0x115) + i)'), 'f')
    assert '(void *) (i + __repair_offset);' in out


def test_left_alone_otherwise():
    assert o.variants(SOURCE.replace('    u8 *base;\n', '    s32 base;\n'), 'f') == []  # not a pointer local
    assert o.variants(SOURCE.replace('(i + (base - 0x115))', '(i + (base - n))'), 'f') == []  # not a constant
    assert o.variants(SOURCE.replace('    M2C_FIELD(arg0, void **, -0x18) = (void *) (i + (base - 0x115));\n',
                                     '    if (i + (base - 0x115)) {\n        g(0);\n    }\n'), 'f') == []  # a condition
