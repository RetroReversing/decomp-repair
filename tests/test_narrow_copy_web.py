from decomprepair.narrow_copy_web import FAMILY, variants

SOURCE = """typedef struct {
    char pad[18];
    u8 kind;
} Save;
extern s16 table[];
void rank(Save *save, s32 index) {
    s32 kind;
    s32 temp;
    s32 id;
    kind = save->kind;
    temp = kind;
    if (temp == 2) {
        temp = 0;
        do {
            temp++;
        } while (temp < index);
        id = temp;
    } else {
        id = 1;
        if (table[temp] >= table[1 - temp]) {
            id = 2;
        }
    }
    use(id, kind);
}
"""


def test_the_copys_reads_move_to_a_local_of_the_members_own_type():
    children = [c for f, c in variants(SOURCE, 'rank') if f == FAMILY]
    assert len(children) == 1
    child = children[0]
    assert 'u8 temp_kind;' in child
    assert 'temp_kind = kind;' in child
    assert 'if (temp_kind == 2)' in child
    assert 'table[temp_kind] >= table[1 - temp_kind]' in child
    assert 'temp = 0;' in child and 'temp++;' in child and 'temp < index' in child  # the loop counter keeps the name
    assert child.index('u8 temp_kind;') < child.index('kind = save->kind;')


def test_a_local_that_is_declared_narrow_gives_its_own_type():
    source = SOURCE.replace('s32 kind;', 'u16 kind;').replace('u8 kind;\n} Save;', 'u8 other;\n} Save;')
    children = [c for f, c in variants(source, 'rank') if f == FAMILY]
    assert children and 'u16 temp_kind;' in children[0]


def test_a_value_that_is_not_shown_to_fit_the_narrow_type_is_left_alone():
    wide = SOURCE.replace('u8 kind;\n} Save;', 's32 kind;\n} Save;')
    assert variants(wide, 'rank') == []
    shared = SOURCE.replace('char pad[18];', 'u8 kind;\n    char pad[18];', 1)
    assert variants(shared.replace('} Save;', '} Save;\ntypedef struct {\n    s32 kind;\n} Other;'), 'rank') == []


def test_a_counter_with_no_second_web_is_not_split():
    only = SOURCE.replace('        temp = 0;\n', '        id = 0;\n')
    assert variants(only.replace('temp++;', 'id++;').replace('temp < index', 'id < index'), 'rank') == []


def test_a_web_that_another_assignment_can_also_reach_is_not_split():
    mixed = SOURCE.replace('    if (temp == 2) {\n        temp = 0;', '    if (index) {\n        temp = 0;\n    }\n    if (temp == 2) {')
    assert variants(mixed, 'rank') == []


def test_a_read_that_is_also_a_write_in_the_web_is_not_split():
    bumped = SOURCE.replace('    if (temp == 2) {', '    temp++;\n    if (temp == 2) {')
    assert variants(bumped, 'rank') == []


def test_an_address_taken_counter_is_not_split():
    assert variants(SOURCE.replace('use(id, kind);', 'use(id, &temp);'), 'rank') == []
