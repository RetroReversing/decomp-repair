"""Pointer tables read with one index in a loop: a user pointer for the hoisted table, a slot pointer per table."""
import re

from decomprepair import loop_table_slot_pointers as p
from decomprepair import registry

SOURCE = '''typedef unsigned short u16;
typedef struct { short x, y, z; short pad; } Vert;
typedef struct { u16 v[4]; } Face;
typedef struct { int pad[46]; int model; } Body;
typedef struct { Body *body; u16 face; u16 pad; } Entry;
extern Vert *VERTS[];
extern Face *FACES[];
extern Entry LIST[];
extern int COUNT;
void use(Vert *, Face *);

void walk(void)
{
    int i;
    Body *body;
    Face *face;
    Vert *vtx;

    for (i = 0; i < COUNT; i++) {
        body = LIST[i].body;
        vtx = VERTS[body->model];
        face = (Face *) &FACES[body->model];
        face = &(*(Face **) face)[LIST[i].face];
        use(vtx, face);
    }
}
'''


def texts(source):
    return [text for _, text in p.variants(source, 'walk')]


def test_the_ray_test_step_from_its_staged_triangle_pointer():
    """The 438-instruction ray test (SN64 GCC 2.8.1 -mfp32): 55 -> 0 with the face table hoisted by a user pointer."""
    want = ('    for (i = 0; i < COUNT; i++) {\n'
            '        face_table = FACES;\n'
            '        body = LIST[i].body;\n'
            '        face_slot = &face_table[body->model];\n'
            '        vtx_slot = &VERTS[body->model];\n'
            '        face = &(*face_slot)[LIST[i].face];\n'
            '        vtx = *vtx_slot;\n'
            '        use(vtx, face);\n')
    found = [text for text in texts(SOURCE) if want in text]
    assert found
    assert '    Face **face_table;\n    Vert **vtx_slot;\n    Face **face_slot;\n' in found[0]


def test_the_shadow_walker_step_from_a_sum_and_a_staged_load():
    """The 761-instruction shadow walker: 195 -> 0 (the triangle pointer a sum, the vertex pointer staged)."""
    source = SOURCE.replace(
        '        vtx = VERTS[body->model];\n'
        '        face = (Face *) &FACES[body->model];\n'
        '        face = &(*(Face **) face)[LIST[i].face];\n',
        '        face = FACES[body->model] + LIST[i].face;\n'
        '        vtx = (Vert *) &VERTS[body->model];\n'
        '        vtx = *(Vert **) vtx;\n')
    want = ('        face_table = FACES;\n'
            '        body = LIST[i].body;\n'
            '        face_slot = &face_table[body->model];\n'
            '        vtx_slot = &VERTS[body->model];\n'
            '        face = *face_slot + LIST[i].face;\n'
            '        vtx = *vtx_slot;\n')
    assert any(want in text for text in texts(source))


def test_the_table_pointer_can_sit_right_before_the_run_and_either_table_is_hoisted():
    out = texts(SOURCE)
    assert any('        body = LIST[i].body;\n        face_table = FACES;\n' in text for text in out)
    assert any('vtx_table = VERTS;' in text and 'vtx_slot = &vtx_table[body->model];' in text for text in out)
    assert len(out) <= p.LIMIT


def test_a_table_whose_element_type_differs_is_cast():
    source = SOURCE.replace('extern Vert *VERTS[];', 'extern void *VERTS[];')
    assert any('vtx_slot = (Vert **) &VERTS[body->model];' in text for text in texts(source))


def test_different_indexes_a_lone_read_or_no_loop_are_left_alone():
    assert texts(SOURCE.replace('VERTS[body->model]', 'VERTS[i]')) == []
    assert texts(SOURCE.replace('        vtx = VERTS[body->model];\n', '')) == []
    flat = SOURCE.replace('    for (i = 0; i < COUNT; i++) {\n', '    i = 0;\n    {\n')
    assert texts(flat) == []


def test_an_index_with_a_call_is_left_alone():
    assert texts(SOURCE.replace('[body->model]', '[next(body)]')) == []


def test_it_is_declared():
    assert registry.problems(next(r for r in registry.declared() if r.module == 'loop_table_slot_pointers')) == []


BLOCK = '''typedef unsigned short u16;
typedef struct { short x, y, z; short pad; } Vert;
typedef struct { u16 v[4]; } Face;
typedef struct { int pad[46]; int model; } Body;
typedef struct { Body *body; u16 face; u16 pad; } Entry;
extern Vert *VERTS[];
extern Face *FACES[];
extern Entry LIST[];
extern int COUNT;
void use(Vert *, Face *);

void walk(void)
{
    int i;

    i = 0;
    if (i < COUNT)
    {
    do
    {
        Body *body = LIST[i].body;
        int model = body->model;
        Vert *vtx = VERTS[model];
        Face *face = &FACES[model][LIST[i].face];

        use(vtx, face);
        i++;
    }
    while (i < COUNT);
    }
}
'''


def test_initialised_block_locals_are_split_and_the_table_pointer_follows_the_declarations():
    """The 537-instruction collision ray test (SN64 GCC 2.8.1): its plain form 5029 -> 4689 (-mfp32 3629 -> 3109).

    Its loop body declares the reads with initialisers; the family offered nothing, and on the split form its `top`
    child put the table pointer above the block's declarations (a C89 error) and spliced its own at a stale offset."""
    want = ('        Body *body;\n'
            '        int model;\n'
            '        Vert *vtx;\n'
            '        Face **face_table;\n'
            '        Vert **vtx_slot;\n'
            '        Face **face_slot;\n'
            '        Face *face;\n'
            '\n'
            '        face_table = FACES;\n'
            '        body = LIST[i].body;\n'
            '        model = body->model;\n'
            '        face_slot = &face_table[model];\n'
            '        vtx_slot = &VERTS[model];\n'
            '        face = &(*face_slot)[LIST[i].face];\n'
            '        vtx = *vtx_slot;\n'
            '        use(vtx, face);\n')
    out = texts(BLOCK)
    assert any(want in text for text in out)
    assert len(out) <= p.LIMIT


def test_no_child_puts_a_statement_before_a_block_declaration():
    split = BLOCK.replace('        Body *body = LIST[i].body;\n        int model = body->model;\n'
                          '        Vert *vtx = VERTS[model];\n        Face *face = &FACES[model][LIST[i].face];\n\n',
                          '        Body *body;\n        int model;\n        Vert *vtx;\n        Face *face;\n\n'
                          '        body = LIST[i].body;\n        model = body->model;\n'
                          '        vtx = VERTS[model];\n        face = &FACES[model][LIST[i].face];\n\n')
    for source in (BLOCK, split):
        out = texts(source)
        assert out
        for text in out:
            body = text[text.index('    do\n    {\n') + len('    do\n    {\n'):]
            lines = [line.strip() for line in body.splitlines()]
            first_statement = next(n for n, line in enumerate(lines) if line and '=' in line)
            assert not any(re.fullmatch(r'\w+\s*\**\s*\w+;', line) for line in lines[first_statement:]
                           if line not in ('i++;',)), text
