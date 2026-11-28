"""expanded_field_record_view: M2C_FIELD's expansion, byte-offset casts, as record members."""
from decomprepair import expanded_field_record_view as s
from decomprepair import registry

SOURCE = '''extern s32 D_80001000;

void unlink(void *arg0) {
    void *temp_v1;

    temp_v1 = (*(void **)((char *)(arg0) + 0x48));
    if (temp_v1 != NULL) {
        (*(void **)((char *)(temp_v1) + 0x4C)) = (void *) (*(void **)((char *)(arg0) + 0x4C));
    }
    (*(void **)((char *)((*(void **)((char *)(arg0) + 0x4C))) + 0x48)) = (void *) (*(void **)((char *)(arg0) + 0x48));
    D_80001000--;
    (*(s32 *)((char *)(arg0) + 0x80)) = 0;
}
'''


def test_pointers_share_a_record_have_their_own_and_stand_alone():
    children = [source for _, source in s.variants(SOURCE, 'unlink')]
    assert len(children) == 5  # shared, one record each, then each of the three bases alone
    shared, each = children[0], children[1]
    assert '(*(' not in shared and '(*(' not in each
    assert '} Rec_unlink;' in shared and 'void *m48;' in shared and 'char pad50[0x30];' in shared
    assert 'temp_v1 = (((Rec_unlink *) arg0)->m48);' in shared
    assert '(((Rec_unlink *) ((Rec_unlink *) arg0)->m4C)->m48) = (void *)' in shared  # a pointer read from a field
    assert 'Rec_unlink_arg0' in each and 'Rec_unlink_temp_v1' in each and 'Rec_unlink_field' in each
    assert shared.index('} Rec_unlink;') < shared.index('void unlink(')
    assert 'D_80001000--;' in shared


def test_one_pointer_has_one_child_in_any_byte_cast():
    source = 'void f(void *a) {\n    *(u8 *)((u8 *)a + 1) = *(u8 *)((s8 *)(a) + 2);\n}\n'
    ((family, child),) = s.variants(source, 'f')
    assert family == 'expanded_field_record_view'
    assert '((Rec_f_a *) a)->m1 = ((Rec_f_a *) a)->m2;' in child


def test_pointers_that_disagree_get_no_shared_record():
    source = 'void f(void *a, void *b) {\n    *(s32 *)((char *)(a) + 4) = 0;\n    *(f32 *)((char *)(b) + 4) = 0;\n}\n'
    children = [child for _, child in s.variants(source, 'f')]
    assert len(children) == 3 and not any('} Rec_f;' in child for child in children)


def test_refuses_what_cannot_be_a_record():
    assert s.variants('void f(void *a) {\n    *(s32 *)((char *)(a) + 2) = 0;\n}\n', 'f') == []  # misaligned
    assert s.variants('void f(void *a) {\n    *(s32 *)((char *)(a) + i) = 0;\n}\n', 'f') == []  # not a constant
    assert s.variants('void f(s32 *a) {\n    *(s32 *)(a + 4) = 0;\n}\n', 'f') == []  # no byte cast
    assert s.variants(SOURCE, 'other') == []


def test_is_declared():
    assert registry.get('expanded_field_record_view') is not None
