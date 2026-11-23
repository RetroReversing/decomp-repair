"""A pointer built from a sum, and a later sum of the same two values that cse must not share."""
from decomprepair import pointer_sum_cse_barrier as p
from decomprepair import registry

SOURCE = '''typedef unsigned int u32;
extern char *gTable;
extern void emit(short *, u32);
extern int gFlag;

void build(int index)
{
    short out[3];
    int stride;
    char *table = gTable;
    void *obj;
    stride = (index * 53) << 2;
    {
        typedef struct { char pad[0x68]; void *object; char pad2[0x2c]; unsigned char kind; } Rec;
        Rec *parent = (Rec *)(table + stride);
        obj = parent->object;
        if (parent->kind == 0xFF) {
            out[0] = gFlag;
            out[1] = gFlag + 1;
            emit(out, (u32)table + (u32)(stride + 0x9C));
        }
    }
    gFlag = (int)obj;
}
'''

EXPECTED = SOURCE.replace('emit(out, (u32)table + (u32)(stride + 0x9C));',
                          'parent = 0; emit(out, (u32)stride + (u32)table + 0x9C);')


def texts(source):
    return [text for _, text in p.variants(source, 'build')]


def test_the_sum_and_the_reassignment_are_one_child():
    """The saved best's 220 -> 120 step: `parent` assigned again, the address written sum first and offset last."""
    assert EXPECTED in texts(SOURCE)


def test_a_sum_already_written_in_the_target_order_gets_only_the_reassignment():
    source = SOURCE.replace('(u32)table + (u32)(stride + 0x9C)', '(u32)stride + (u32)table + 0x9C')
    assert source.replace('emit(out,', 'parent = 0; emit(out,') in texts(source)


def test_a_pointer_read_after_the_sum_is_left_alone():
    source = SOURCE.replace('emit(out, (u32)table + (u32)(stride + 0x9C));',
                            'emit(out, (u32)table + (u32)(stride + 0x9C)); gFlag += parent->kind;')
    assert texts(source) == []


def test_a_sum_of_other_values_is_left_alone():
    assert texts(SOURCE.replace('(u32)table + (u32)(stride + 0x9C)', '(u32)table + (u32)(index + 0x9C)')) == []


def test_a_pointer_never_read_after_its_sum_is_left_alone():
    source = SOURCE.replace('obj = parent->object;', 'obj = 0;').replace('parent->kind == 0xFF', 'gFlag == 0xFF')
    assert texts(source) == []


def test_an_else_branch_is_not_split():
    source = SOURCE.replace('        }\n    }', '        } else emit(out, (u32)table + (u32)(stride + 0x9C));\n    }')
    for text in texts(source):
        assert 'parent = 0; else' not in text and 'else parent = 0' not in text.replace('else emit', 'else  emit')


def test_it_declares_itself():
    repair = registry.get('pointer_sum_cse_barrier')
    assert repair is not None and not registry.problems(repair)
    assert 'pointer_sum_cse_barrier' in repair.families
