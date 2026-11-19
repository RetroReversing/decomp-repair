"""A symbol's address held in a local pointer where m2c named the symbol at each use."""
from decomprepair import symbol_base_repairs as b

TABLE = '''extern char D_800E4290[];

s32 f(void *arg0) {
    s32 *var_v0;
    u8 temp_v1;

    temp_v1 = M2C_FIELD(arg0, u8 *, 0x4B);
    if (temp_v1 != 0xFF) {
        var_v0 = (temp_v1 * 4) + D_800E4290;
    } else {
        var_v0 = D_800E4290 + 0x20;
    }
    return *var_v0;
}
'''

SCALAR = '''extern s32 D_8010968C;

void f(void *arg0) {
    if (arg0 != NULL) {
        g(arg0);
        h(D_8010968C, 0xE);
        D_8010968C = 0;
    }
}
'''

ADDRESS = '''extern s16 D_800B7D1C;
extern s32 D_800B7D20;

void f(s32 arg0) {
    if (D_800B7D20 == 0) {
        D_800B7D1C = arg0 & 0xFF;
        D_800B7D20 = g(&D_800B7D1C - 0x20);
    }
}
'''


def test_a_table_through_a_pointer_set_at_its_use_and_at_the_top():
    # An N64 function at 51.8%: exact with the pointer set at the top of the function.
    texts = [t for _, t in b.variants(TABLE, 'f')]
    assert len(texts) == 2
    assert all('__base_D_800E4290 = D_800E4290;' in t and '(temp_v1 * 4) + __base_D_800E4290' in t for t in texts)
    assert '    char *__base_D_800E4290;' in texts[0]


def test_a_scalar_read_and_cleared_across_a_call():
    # An N64 function at 62.3% kept the global's address in a saved register across the call: exact so.
    (family, out), *_ = b.variants(SCALAR, 'f')
    assert family == 'symbol_address_local'
    assert '__base_D_8010968C = &D_8010968C;' in out
    assert 'h((*__base_D_8010968C), 0xE);' in out and '(*__base_D_8010968C) = 0;' in out


def test_a_taken_address_and_its_element_step():
    # An N64 function at 64.7%: the game stepped 0x20 bytes back, which on an s16 pointer is 0x10.
    texts = [t for _, t in b.variants(ADDRESS, 'f')]
    assert any('g(__base_D_800B7D1C - 0x10)' in t for t in texts)
    assert any('g(__base_D_800B7D1C - 0x20)' in t for t in texts)


def test_left_alone_otherwise():
    assert b.variants(TABLE.replace('(temp_v1 * 4) + D_800E4290', 'D_800E4290[temp_v1 * 4]')
                      .replace('D_800E4290 + 0x20', '&D_800E4290[0x20]'), 'f') == []
    assert b.variants(SCALAR.replace('        D_8010968C = 0;\n', ''), 'f') == []
