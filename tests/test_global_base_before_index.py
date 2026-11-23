"""A global base pointer read into a local before the index statement that is added to it."""
from decomprepair import global_base_before_index as g
from decomprepair import registry

SOURCE = '''typedef unsigned int u32;
extern char *gTable;
extern int gScale;
extern void use(short *, char *);
extern void other(char *);

void walk(int arg, short *out, float *src)
{
    int off;
    out[0] = (short)(int)src[0];
    off = arg * 0xD4;
    out[1] = (short)(int)src[1];
    out[2] = (short)(int)(src[2] + (float)*(short *)((char *)(gTable + off) + 0x96));
    off += 0x14;
    use(out, gTable + off + 0x88);
    other(gTable + off + 0x88);
}
'''

HEADER = ''


def texts(source, header=HEADER):
    return [text for _, text in g.variants(source, 'walk', header)]


def test_the_base_is_read_before_the_index_statement_and_used_up_to_the_call():
    """The matrix function's 120 -> 0 step: the local first, `base + off` for both reads before the call."""
    expected = (SOURCE.replace('{\n    int off;', '{ char * gTable_base;\n    int off;')
                .replace('    off = arg * 0xD4;', '    gTable_base = gTable; off = arg * 0xD4;')
                .replace('(char *)(gTable + off)', '(char *)(gTable_base + off)')
                .replace('use(out, gTable + off + 0x88);', 'use(out, gTable_base + off + 0x88);'))
    assert texts(SOURCE) == [expected]


def test_the_read_after_the_first_call_keeps_the_global():
    for text in texts(SOURCE):
        assert 'other(gTable + off + 0x88)' in text


def test_a_single_read_is_not_enough():
    assert texts(SOURCE.replace('    use(out, gTable + off + 0x88);\n', '    use(out, 0);\n')) == []


def test_a_global_assigned_in_the_run_is_left_alone():
    assert texts(SOURCE.replace('    off += 0x14;', '    gTable = 0;\n    off += 0x14;')) == []


def test_a_volatile_global_is_left_alone():
    assert texts(SOURCE.replace('extern char *gTable;', 'extern char * volatile gTable;')) == []


def test_the_global_may_be_declared_in_the_header():
    source = SOURCE.replace('extern char *gTable;\n', '')
    assert texts(source) == []
    assert texts(source, 'extern char *gTable;') != []


def test_an_index_that_is_not_a_product_is_left_alone():
    assert texts(SOURCE.replace('off = arg * 0xD4;', 'off = arg + 0xD4;')) == []


def test_it_declares_itself():
    repair = registry.get('global_base_before_index')
    assert repair is not None and not registry.problems(repair)
    assert 'global_base_before_index' in repair.families
