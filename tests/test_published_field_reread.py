from decomprepair.published_field_reread import FAMILY, variants

M2C = '''void f(void *arg0) {
    void *temp_v0;

    if (arg0 != NULL) {
        temp_v0 = M2C_FIELD(arg0, void **, 0x48);
        M2C_FIELD(arg0, void **, 0x50) = temp_v0;
        M2C_FIELD(temp_v0, s32 *, 0x4C) = 0;
        M2C_FIELD(arg0, void **, 0x48) = NULL;
    }
}
'''


def children(source):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_m2c_draft_reads_the_field_again():
    [child] = children(M2C)
    assert ('        M2C_FIELD(arg0, void **, 0x50) = M2C_FIELD(arg0, void **, 0x48);\n'
            '        temp_v0 = M2C_FIELD(arg0, void **, 0x48);\n'
            '        M2C_FIELD(temp_v0, s32 *, 0x4C) = 0;\n') in child


def test_struct_spellings():
    shapes = ('n = obj->cur; obj->prev = n;', 'obj->prev = obj->cur; n = obj->prev;', 'n = obj->prev = obj->cur;',
              'obj->prev = n = obj->cur;')
    for shape in shapes:
        source = 'void f(Obj *obj) {\n    Node *n;\n    ' + shape + '\n    n->link = 0;\n}\n'
        [child] = children(source)
        assert 'obj->prev = obj->cur;\n    n = obj->cur;' in child, shape
        assert not children(child)


def test_several_sites_add_a_combined_child():
    source = M2C.replace('        M2C_FIELD(arg0, void **, 0x48) = NULL;\n',
                         '        temp_v0 = D_80010000;\n        D_80010004 = temp_v0;\n'
                         '        M2C_FIELD(temp_v0, s32 *, 0) = 0;\n')
    found = children(source)
    assert len(found) == 3
    assert 'D_80010004 = D_80010000;' in found[-1] and 'temp_v0 = M2C_FIELD(arg0, void **, 0x48);' in found[-1]


def test_declines_what_would_change_the_program():
    base = 'void f(Obj *obj) {\n    %s n;\n    %s\n    use(n);\n}\n'
    # a narrower local would truncate; a call must not run twice; a volatile read must stay one; a local is no memory
    assert not children(base % ('s16', 'n = obj->cur; obj->prev = n;'))
    assert not children(base % ('Node *', 'n = next(obj); obj->prev = n;'))
    assert not children(base % ('Node *', 'n = obj->cur; ((volatile Obj *) obj)->prev = n;'))
    assert not children(base % ('Node *', 'Node *m;\n    n = obj->cur; m = n;'))
    # the lvalue names the local, or the local is never used again
    assert not children(base % ('Node *', 'n = obj->cur; n->prev = n;'))
    assert not children('void f(Obj *obj) {\n    Node *n;\n    n = obj->cur; obj->prev = n;\n}\n')
