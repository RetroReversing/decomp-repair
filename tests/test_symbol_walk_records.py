from decomprepair import symbol_walk_records

DRAFT = """extern char table[];

void f(void) {
    s32 v;
    void *var_t1;

    var_t1 = table + 0xC0;
    do {
        M2C_FIELD(var_t1, s32 *, 0) = -1;
        M2C_FIELD(var_t1, s32 *, 8) = 0;
        for (;;) {
            v = g();
            if (v < 0) {
                continue;
            }
            break;
        }
        M2C_FIELD(var_t1, s32 *, 4) = v;
        var_t1 += 0xC;
    } while ((u32) var_t1 < (u32) (table + 0x240));
}
"""


def test_the_walk_becomes_indexed_records():
    out = symbol_walk_records.variants(DRAFT, 'f')
    assert [family for family, _ in out] == ['symbol_walk_records']
    text = out[0][1]
    assert 'typedef struct {\n    s32 unk0;\n    s32 unk4;\n    s32 unk8;\n} table_row;\nvoid f(void) {' in text
    assert '    var_t1_index = 16;\n' in text
    assert '((table_row *) table)[var_t1_index].unk4 = v;' in text
    assert 'var_t1_index++;' in text
    assert '} while (var_t1_index < 48);' in text


def test_a_continue_of_the_walk_itself_or_another_use_refuses():
    assert not symbol_walk_records.variants(DRAFT.replace('var_t1 += 0xC;', 'if (v) { continue; }\n        var_t1 += 0xC;'), 'f')
    assert not symbol_walk_records.variants(DRAFT.replace('v = g();', 'v = g(var_t1);'), 'f')
    assert not symbol_walk_records.variants(DRAFT.replace('0x240', '0x244'), 'f')
