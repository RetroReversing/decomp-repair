"""A pointer local set from the loop counter at the top of a loop body, written into each arm that reads it."""
from decomprepair import loop_giv_local_arm_inline as p
from decomprepair import registry

SOURCE = '''typedef unsigned short u16;
typedef int s32;
typedef struct { u16 used; char name[17]; char code[5]; } Entry;
typedef struct { s32 clear; char text[28]; } Raw;
extern Entry gEntries[];
extern Raw gRaw[];
extern s32 gResult;
extern s32 wait(void);
extern void submit(s32, s32, Raw *);
extern void decode(char *, char *, s32);

void scan(void)
{
    char *name;
    char *code;
    s32 i;
    s32 j;
    i = 0;
    do
    {
        name = gEntries[i].name;
        code = gEntries[i].code;
        submit(5, i, &gRaw[i]);
        if (wait() == 5)
        {
            gEntries[i].used = 0;
            j = 15;
            do { name[j] = 32; } while (--j >= 0);
            name[16] = 0;
            j = 3;
            do { code[j] = 32; } while (--j >= 0);
            code[4] = 0;
            gRaw[i].clear = 0;
            gResult = 0;
        }
        else
        {
            gEntries[i].used = 1;
            decode(name, gRaw[i].text, 16);
            decode(code, gRaw[i].text, 4);
        }
        i++;
    }
    while (i < 16);
}
'''


def texts(source, name='scan'):
    return [text for _, text in p.variants(source, name)]


def test_every_read_is_the_expression_and_the_offset_store_keeps_a_local_set_just_before_it():
    text = texts(SOURCE)[0]
    assert 'name = gEntries[i].name;' not in text and 'code = gEntries[i].code;' not in text
    assert 'char *name;' not in text and 'char *code;' not in text
    assert 'do { gEntries[i].name[j] = 32; } while (--j >= 0);' in text
    assert 'name_1 = gEntries[i].name;\n            name_1[16] = 0;' in text
    assert 'code_1 = gEntries[i].code;\n            code_1[4] = 0;' in text
    assert 'decode(gEntries[i].name, gRaw[i].text, 16);' in text
    assert 'decode(gEntries[i].code, gRaw[i].text, 4);' in text
    assert 'char *name_1;' in text and 'char *code_1;' in text


def test_the_child_with_every_local_comes_first_then_each_local_alone():
    children = texts(SOURCE)
    assert len(children) == 3
    assert 'char *code;' in children[1] and 'char *name;' not in children[1]
    assert 'char *name;' in children[2] and 'char *code;' not in children[2]


def test_a_local_read_in_one_statement_only_is_left_alone():
    source = SOURCE.replace('decode(code, gRaw[i].text, 4);', 'decode(name, gRaw[i].text, 4);') \
        .replace('do { code[j] = 32; } while (--j >= 0);', 'j = 0;').replace('            code[4] = 0;\n', '')
    assert all('code = gEntries[i].code;' in text for text in texts(source))


def test_a_local_that_is_assigned_again_is_not_a_counter_derived_constant():
    source = SOURCE.replace('        i++;\n', '        name = gEntries[0].code;\n        i++;\n')
    assert all('name_1' not in text for text in texts(source))


def test_a_value_that_names_no_loop_counter_is_not_offered():
    source = SOURCE.replace('name = gEntries[i].name;', 'name = gEntries[0].name;').replace('code = gEntries[i].code;', 'code = gEntries[1].code;')
    assert texts(source) == []


def test_a_value_with_a_call_is_not_offered():
    source = SOURCE.replace('name = gEntries[i].name;', 'name = pick(gEntries[i].name);')
    assert all('name = pick(gEntries[i].name);' in text for text in texts(source))


def test_a_loop_body_without_an_if_is_not_offered():
    source = SOURCE.replace('if (wait() == 5)', 'if (0 && wait() == 5)').replace('if (', 'while (')
    assert texts(source) == []


def test_a_local_read_after_the_loop_is_not_offered():
    source = SOURCE.replace('    while (i < 16);\n}', '    while (i < 16);\n    gResult = name[0] + code[0];\n}')
    assert texts(source) == []


def test_the_module_declares_itself_in_the_registry():
    repair = registry.get('loop_giv_local_arm_inline')
    assert repair and registry.problems(repair) == []
