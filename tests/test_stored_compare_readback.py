from decomprepair import registry
from decomprepair.stored_compare_readback import FAMILY, FAMILY_DEAD_COPY, variants

SEED = """void func(void *arg0) {
    s32 t;
    s32 x;

    x = *(u8 *)((s8 *)arg0 + 0x73);
    t = (*(s32 *)((s8 *)arg0 + 0x34)) + 1;
    (*(s32 *)((s8 *)arg0 + 0x34)) = t;
    (*(u8 *)((s8 *)arg0 + 0x73)) = (u8) (x + 1);
    (*(u8 *)((s8 *)arg0 + 0x72)) = x;
    (*(u8 *)((s8 *)arg0 + 0x71)) = x;
    if (t >= 0x3D) {
        other(0x5E);
    }
}
"""


def test_the_condition_reads_the_stored_field_back():
    children = variants(SEED, 'func')
    assert [f for f, _ in children] == [FAMILY]
    assert children[0][1] == SEED.replace('if (t >= 0x3D)', 'if ((*(s32 *)((s8 *)arg0 + 0x34)) >= 0x3D)')


def test_arrow_members_and_the_field_macro():
    typed = """typedef struct { s32 timer; u8 f4; } Obj;
void func(Obj *o) {
    s32 t;
    t = o->timer + 1;
    o->timer = t;
    o->f4 = 0;
    if (t >= 3) {
        o->f4 = 1;
    }
}
"""
    assert 'if (o->timer >= 3)' in variants(typed, 'func')[0][1]
    macro = """void func(void *p) {
    s32 t;
    M2C_FIELD(p, s32 *, 4) = t;
    M2C_FIELD(p, u8 *, 8) = 0;
    if (t != 0) {
        t = 1;
    }
}
"""
    assert 'if (M2C_FIELD(p, s32 *, 4) != 0)' in variants(macro, 'func')[0][1]


def test_nothing_across_a_call_an_overlap_another_base_or_a_change_of_type():
    for between in ('other();', '*(u8 *)((s8 *)p + 5) = 0;', '*(u8 *)((s8 *)q + 8) = 0;', 't = 2;', '*p = 0;'):
        source = f"""void func(void *p, void *q) {{
    s32 t;
    *(s32 *)((s8 *)p + 4) = t;
    {between}
    if (t > 1) {{
        t = 0;
    }}
}}
"""
        assert variants(source, 'func') == [], between
    unsigned = SEED.replace('s32 t;', 'u32 t;')
    assert variants(unsigned, 'func') == []


def test_registered():
    assert any(r.module == 'stored_compare_readback' for r in registry.declared())


def test_a_local_set_only_in_a_dead_block_reads_as_the_local_it_copied():
    kept = """void func(void *arg0) {
    s32 t;
    s32 copy;

    loop_goto_2:
    {
        t = (*(s32 *)((s8 *)arg0 + 0x34)) + 1;
    }
    if (0)
    {
        copy = t;
        do { goto loop_goto_2; } while (0);
    }
    (*(s32 *)((s8 *)arg0 + 0x34)) = copy;
    if (t >= 0x3D) {
        other(0x5E);
    }
}
"""
    found = [c for f, c in variants(kept, 'func') if f == FAMILY_DEAD_COPY]
    assert len(found) == 1
    assert 'goto' not in found[0] and '= t;' in found[0]
    assert 'if ((*(s32 *)((s8 *)arg0 + 0x34)) >= 0x3D)' in found[0]
    assert variants(kept.replace('copy = t;', 'copy = t;\n        t = 0;'), 'func') == []
