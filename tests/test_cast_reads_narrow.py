"""A word local only ever read through one narrow cast, declared that narrow."""
from decomprepair import cast_reads_narrow as p
from decomprepair import registry

SOURCE = '''void spawn(s32 *out)
{
    u32 angle;

    angle = rand() >> 3;
    out[1] = sine((s16) angle);
    out[2] = cosine((s16) angle);
}
'''


def test_the_local_takes_the_cast_type():
    [(family, child)] = p.variants(SOURCE, 'spawn')
    assert family == p.FAMILY
    assert 's16 angle;' in child and '(s16)' not in child
    assert 'sine(angle)' in child and 'cosine(angle)' in child


def test_several_locals_come_together_first():
    two = SOURCE.replace('    u32 angle;\n', '    u32 angle;\n    s32 kind;\n').replace(
        '    out[1]', '    kind = out[0];\n    out[3] = (u8) kind;\n    out[1]')
    children = [child for _, child in p.variants(two, 'spawn')]
    assert len(children) == 3
    assert 's16 angle;' in children[0] and 'u8 kind;' in children[0]


def test_declined_when_the_word_is_needed():
    bare = SOURCE.replace('cosine((s16) angle)', 'cosine(angle)')
    mixed = SOURCE.replace('cosine((s16) angle)', 'cosine((u16) angle)')
    shifted = SOURCE.replace('    out[1]', '    angle >>= 2;\n    out[1]')
    address = SOURCE.replace('    out[1]', '    keep(&angle);\n    out[1]')
    chained = SOURCE.replace('angle = rand() >> 3;', 'out[0] = angle = rand() >> 3;')
    for source in (bare, mixed, shifted, address, chained):
        assert p.variants(source, 'spawn') == [], source


def test_the_module_declares_itself():
    assert any(repair.module == 'cast_reads_narrow' for repair in registry.declared())
