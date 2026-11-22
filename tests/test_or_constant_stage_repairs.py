"""A packed word's constant joins the low field in a local first."""
from decomprepair import or_constant_stage_repairs as o

SOURCE = '''void f(u8 *p, s32 pitch, s32 r)
{
  *((s32 *) p) = (((pitch & 0xFF) << 16) | ((r + 1) << 8)) | 0x19;
  g(p);
}
'''


def test_the_constant_joins_the_low_field_first():
    # A KMC N64 function: 160 -> 95 (the ori on the low field, then the or).
    (family, out), = o.variants(SOURCE, 'f')
    assert family == 'or_constant_stage'
    assert ('  {\n    u32 __repair_or = ((r + 1) << 8) | 0x19;\n'
            '    *((s32 *) p) = ((pitch & 0xFF) << 16) | __repair_or;\n  }\n') in out
    assert '  g(p);' in out


def test_left_alone_otherwise():
    assert o.variants(SOURCE.replace(' | 0x19', ''), 'f') == []  # no constant
    assert o.variants(SOURCE.replace('(((pitch & 0xFF) << 16) | ((r + 1) << 8))', '((pitch & 0xFF) << 16)'), 'f') == []
    assert o.variants(SOURCE.replace('*((s32 *) p) = ', 'if '), 'f') == []  # a condition, not a store
    assert o.variants(SOURCE.replace('| ((r + 1) << 8)', '|| ((r + 1) << 8)'), 'f') == []  # a logical or
