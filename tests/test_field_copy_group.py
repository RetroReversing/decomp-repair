"""field_copy_group: a spawned record's field copies stand together before the constants stored beside them."""
from decomprepair import field_copy_group as group
from decomprepair import registry

SOURCE = '''typedef struct Obj {
    u16 x;
    u16 y;
    s32 type;
    u8 state;
    u16 timer;
} Obj;
Obj *spawn(void);
void use(Obj *parent);
void func_spawn(Obj *parent) {
    Obj *first;
    Obj *kept;
    Obj *spark;

    first = spawn();
    if (first != 0) {
        kept = first;
        kept->x = parent->x;
        first = NULL;
        kept->state = 2;
        kept->type = 0x3F7;
        kept->y = parent->y;
        use(parent);
    }
    spark = spawn();
    if (spark != 0) {
        spark->x = parent->x;
        spark->type = 0x3F7;
        spark->y = parent->y;
        spark->state = 3;
        use(parent);
    }
}
'''


def test_both_runs_are_grouped_in_one_child_with_each_literal_order():
    out = group.variants(SOURCE, 'func_spawn')
    assert out and {family for family, _ in out} == {group.FAMILY}
    spark = SOURCE.replace('''        spark->type = 0x3F7;
        spark->y = parent->y;
''', '''        spark->y = parent->y;
        spark->type = 0x3F7;
''')
    written = spark.replace('''        kept->state = 2;
        kept->type = 0x3F7;
        kept->y = parent->y;
''', '''        kept->y = parent->y;
        kept->state = 2;
        kept->type = 0x3F7;
''')
    reversed_ = spark.replace('''        kept->state = 2;
        kept->type = 0x3F7;
        kept->y = parent->y;
''', '''        kept->y = parent->y;
        kept->type = 0x3F7;
        kept->state = 2;
''')
    children = [child for _, child in out]
    assert children[0] == written
    assert reversed_ in children
    assert len(children) <= group.LIMIT


def test_cast_spellings_are_read():
    source = '''void *spawn(void);
void f(void *a) {
    void *o;

    o = spawn();
    (*(u16 *)((char *)(o) + 0)) = (u16) (*(u16 *)((char *)(a) + 0));
    (*(s32 *)((char *)(o) + 0x80)) = 0x3F7;
    (*(u16 *)((char *)(o) + 2)) = (u16) (*(u16 *)((char *)(a) + 2));
}
'''
    wanted = source.replace('''    (*(s32 *)((char *)(o) + 0x80)) = 0x3F7;
    (*(u16 *)((char *)(o) + 2)) = (u16) (*(u16 *)((char *)(a) + 2));
''', '''    (*(u16 *)((char *)(o) + 2)) = (u16) (*(u16 *)((char *)(a) + 2));
    (*(s32 *)((char *)(o) + 0x80)) = 0x3F7;
''')
    assert [child for _, child in group.variants(source, 'f')] == [wanted]


def test_a_record_another_pointer_may_name_and_an_overlapping_cell_are_left_alone():
    given = '''void f(Obj *parent, Obj *o) {
    o->x = parent->x;
    o->type = 1;
    o->y = parent->y;
}
'''
    assert group.variants(given, 'f') == []
    overlap = '''void *spawn(void);
void f(void *a) {
    void *o;

    o = spawn();
    M2C_FIELD(o, s32 *, 0) = 1;
    M2C_FIELD(o, u16 *, 2) = M2C_FIELD(a, u16 *, 2);
}
'''
    assert group.variants(overlap, 'f') == []


def test_it_declares_itself():
    assert any(entry.module == 'field_copy_group' for entry in registry.declared())
