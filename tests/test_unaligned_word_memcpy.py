from decomprepair import registry
from decomprepair import unaligned_word_memcpy as repair

SOURCE = """extern char D_80004000[];
extern char D_80070000[];
extern s32 D_80070100;

void f(s32 i, char *p) {
    *(s32 *)((i * 4) + D_80070000) = M2C_UNALIGNED32(D_80004000);
    M2C_FIELD(p, s32 *, 4) = M2C_UNALIGNED32(D_80070100);
}
"""


def test_each_copy_becomes_a_byte_memcpy_all_at_once_first():
    children = [child for _, child in repair.variants(SOURCE, 'f')]
    assert len(children) == 3
    assert '__builtin_memcpy((char *) ((i * 4) + D_80070000), (char *) D_80004000, 4);' in children[0]
    assert '__builtin_memcpy((char *) ((char *) (p) + 4), (char *) &D_80070100, 4);' in children[0]
    assert 'M2C_UNALIGNED32' not in children[0]


def test_an_address_it_cannot_read_is_left_alone():
    assert not repair.variants('void f(void) { x.y = M2C_UNALIGNED32(z.w); }', 'f')


def test_it_is_registered():
    assert repair.FAMILY in str(registry.declared())
