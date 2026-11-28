"""A global index read into a local before the global pointer it indexes."""
from decomprepair import registry
from decomprepair.global_index_staged import FAMILY, variants

SOURCE = """extern Record *gRecords;
extern s32 gCount;

void append(u32 n)
{
    Record *out;
    u32 i;

    out = &gRecords[gCount];
    for (i = 0; i < n; i++) {
        out->value = 0;
        out++;
        gCount++;
    }
}
"""


def test_the_index_is_read_first_although_the_function_advances_it():
    [(family, child)] = variants(SOURCE, 'append')
    assert family == FAMILY
    assert '{\n    s32 __repair_index;' in child
    assert '    __repair_index = gCount;\n    out = &gRecords[__repair_index];\n' in child
    assert 'gCount++;' in child


def test_a_sum_in_either_order_and_globals_from_the_header():
    header = 'extern Record *gRecords;\nextern u16 gCount;\n'
    for expression in ('gCount + gRecords', 'gRecords + gCount'):
        [(_, child)] = variants(f'void f(void)\n{{\n    Record *out;\n    out = {expression};\n}}\n', 'f', header)
        assert 'u16 __repair_index;' in child and '__repair_index = gCount;' in child
        assert expression.replace('gCount', '__repair_index') in child


def test_statements_that_cannot_take_a_statement_before_them_are_left_alone():
    header = 'extern Record *gRecords;\nextern s32 gCount;\n'
    for body in ('    if (n) p = &gRecords[gCount];\n',
                 '    p = lookup(&gRecords[gCount]);\n',
                 '    Record *q = &gRecords[gCount];\n',
                 '    gRecords[gCount++].value = 0;\n',
                 '    gCount = gRecords[gCount].next;\n',
                 '    for (p = &gRecords[gCount]; p; p++) {}\n',
                 '    p = &local[gCount];\n',
                 '    p = &gRecords[gCount * 2];\n'):
        assert variants('void f(s32 n)\n{\n' + body + '}\n', 'f', header) == [], body


def test_registry_declares_the_family():
    repair = registry.get(FAMILY)
    assert repair is not None and registry.problems(repair) == [] and FAMILY in repair.families
