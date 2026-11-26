"""A pointer read from a table of pointers, with the slot's address staged in the pointer itself."""
from decomprepair import registry
from decomprepair import table_slot_self_stage as p

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
        face = &FACES[body->model][LIST[i].face];
        use(vtx, face);
    }
}
'''


def texts(source):
    return [text for _, text in p.variants(source, 'walk')]


def test_an_element_pointer_is_staged_in_place():
    """The 438-instruction ray test's step (210 -> 55 under -mfp32): the face pointer through its own slot."""
    staged = ('        vtx = VERTS[body->model];\n'
              '        face = (Face *) &FACES[body->model];\n'
              '        face = &(*(Face **) face)[LIST[i].face];\n'
              '        use(vtx, face);')
    assert any(staged in text for text in texts(SOURCE))


def test_a_loaded_pointer_is_staged_and_moved_after_the_next_statement():
    """The 761-instruction walker's step: the vertex pointer staged after the face pointer's statement."""
    staged = ('        face = &FACES[body->model][LIST[i].face];\n'
              '        vtx = (Vert *) &VERTS[body->model];\n'
              '        vtx = *(Vert **) vtx;\n'
              '        use(vtx, face);')
    assert any(staged in text for text in texts(SOURCE))


def test_a_sum_keeps_its_offset():
    source = SOURCE.replace('&FACES[body->model][LIST[i].face]', 'FACES[body->model] + LIST[i].face')
    assert any('face = (Face *) &FACES[body->model];\n        face = *(Face **) face + LIST[i].face;' in text
               for text in texts(source))


def test_an_index_with_a_call_or_the_pointer_itself_is_left_alone():
    source = SOURCE.replace('VERTS[body->model]', 'VERTS[next()]').replace(
        '&FACES[body->model][LIST[i].face]', '&FACES[body->model][face->v[0]]')
    assert texts(source) == []


def test_a_non_pointer_local_is_left_alone():
    source = SOURCE.replace('    Vert *vtx;\n', '    Vert vtxs;\n    int vtx;\n').replace(
        '        face = &FACES[body->model][LIST[i].face];\n', '')
    assert texts(source) == []


def test_it_is_declared():
    assert registry.problems(next(r for r in registry.declared() if r.module == 'table_slot_self_stage')) == []
