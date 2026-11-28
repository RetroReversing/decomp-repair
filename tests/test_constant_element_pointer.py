"""A call's members of a constant-index record, read through a pointer to the record."""
import re

from decomprepair.constant_element_pointer import FAMILY, variants

CODE = '''typedef struct { char name[16]; int x; int y; } Item;
extern void draw(char *, int, int);
extern int next(void);
void run(Item *items, int i)
{
    draw(items[2].name, items[2].x, items[2].y);
    if (i) {
        draw(items[3].name, items[3].x, items[3].y);
    }
    draw(items[0].name, items[0].x, items[0].y);
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_every_record_at_once_then_one_at_a_time():
    children = variants(CODE, 'run')
    assert [family for family, _ in children] == [FAMILY] * 3
    text = squash(children[0][1])
    assert '{ Item *element = &items[2]; draw(element->name, element->x, element->y); }' in text
    assert '{ Item *element = &items[3]; draw(element->name, element->x, element->y); }' in text
    assert 'draw(items[0].name, items[0].x, items[0].y);' in text
    assert 'items[3].x' in children[1][1] and 'items[2].x' not in children[1][1]


def test_an_extern_array_in_the_header_names_the_type():
    code = 'extern void draw(char *, int, int);\nvoid run(void)\n{\n    draw(table[1].name, table[1].x, table[1].y);\n}\n'
    text = variants(code, 'run', header='extern Item table[];\n')[0][1]
    assert 'Item *element = &table[1];' in text


def test_a_prototypes_parameter_of_the_same_name_does_not_name_the_type():
    other = 'typedef struct { int pad; int x; int y; } Other;\nextern void use(Other *items);\n'
    text = variants(CODE, 'run', header=other)[0][1]
    assert 'Item *element = &items[2];' in text and 'Other *' not in text
    code = 'extern void f(int, int);\nvoid run(void)\n{\n    f(items[1].x, items[1].y);\n}\n'
    assert variants(code, 'run', header=other) == []
    # a local in a form not read hides the global of the same name
    shadow = code.replace('{\n    f(', '{\n    Other n, *items;\n    f(')
    assert variants(shadow, 'run', header='extern Item items[];\n') == []


def test_other_shapes_are_left_alone():
    one = 'typedef struct { int x; int y; } P;\nvoid run(P *p)\n{\n    %s\n}\n'
    assert variants(one % 'f(p[1].x, p[2].y);', 'run') == []  # one member of each
    assert variants(one % 'f(p[1].x, p[1].y, next());', 'run') == []  # a call may change what is read
    assert variants(one % 'f(p[1].x, p[1].y++);', 'run') == []
    assert variants(one % 'f(p[1].x, p[1].y = 2);', 'run') == []
    assert variants(one % 'n = (int) f(p[1].x, p[1].y);', 'run') == []  # not a statement of its own
    assert variants(one % '(void) f(p[1].x, p[1].y);', 'run') == []
    assert variants(one % 'f(p[i].x, p[i].y);', 'run') == []
    assert variants(CODE, 'missing') == []
