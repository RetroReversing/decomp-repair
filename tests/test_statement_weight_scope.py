"""One loop statement in a one-shot scope: a macro read or a store of a local (an N64 bit-stream decoder, 1285 -> 0)."""
from decomprepair.statement_weight_scope import MACRO_FAMILY, STORE_FAMILY, variants

SOURCE = """#define READ(dst, n) dst = take(&p, n)

void decode(Dec *o, s32 n2)
{
    u8 *p;
    s32 j;
    s32 y;
    s32 sz;

    p = o->p;
    READ(y, 4);
    for (j = 0; j < o->count; j++) {
        y = sz = 0;
        if (o->flag != 0) {
            READ(sz, n2);
        }
        o->cur[j].v[1] = y;
        o->cur[j].v[8] += sz;
        o->total = j + 1;
    }
    o->p = p;
}
"""


def test_each_loop_statement_gets_its_own_child():
    found = variants(SOURCE, 'decode')
    assert [family for family, _ in found] == [MACRO_FAMILY, STORE_FAMILY, STORE_FAMILY]
    assert '            do {\n                READ(sz, n2);\n            } while (0);\n' in found[0][1]
    assert '        do {\n            o->cur[j].v[1] = y;\n        } while (0);\n' in found[1][1]
    assert '        do {\n            o->cur[j].v[8] += sz;\n        } while (0);\n' in found[2][1]


def test_statements_outside_loops_scoped_already_or_not_plain_are_left_alone():
    found = variants(SOURCE, 'decode')
    assert all('do {\n        READ(y, 4);' not in text for _, text in found)
    assert all('do {\n        o->p = p;' not in text for _, text in found)
    scoped = SOURCE.replace('            READ(sz, n2);\n', '            do {\n                READ(sz, n2);\n            } while (0);\n')
    assert [family for family, _ in variants(scoped, 'decode')] == [STORE_FAMILY, STORE_FAMILY]
    assert variants(SOURCE.replace('#define READ(dst, n)', '#define READ_(dst, n)'), 'decode')[0][0] == STORE_FAMILY


def test_a_macro_from_the_header_counts():
    source = SOURCE.replace('#define READ(dst, n) dst = take(&p, n)\n', '')
    assert variants(source, 'decode', '#define READ(dst, n) dst = take(&p, n)\n')[0][0] == MACRO_FAMILY
