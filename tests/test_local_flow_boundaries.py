"""An incomplete repair view gives no liveness advice, never an uncaught worker error."""
import pytest

from decomprepair import branch_call_support, conversion_scheduling_repairs, local_flow
from decomprepair.csource import _code_only
from decomprepair.integer_repair_support import view


@pytest.mark.parametrize('source', [
    'int sample(int input) { int value = input; return value;',
    'int sample(int input) { int value = input; if (input) { return value; }',
    # Valid after either preprocessor choice; blanking directives leaves two opening braces.
    'int sample(int input)\n#ifdef PORT\n{\n#else\n{\n#endif\nint value = input; return value;\n}',
])
def test_unclosed_view_is_declined_by_flow_and_scheduling(source):
    clean = _code_only(source)
    part = view(clean, 'sample')
    assert part is not None
    with pytest.raises(ValueError, match='unclosed function'):
        local_flow.Flow(part)
    assert local_flow.analyze(clean, 'sample') is None
    assert branch_call_support.facts(clean, 'sample', arch='mips') is None
    assert conversion_scheduling_repairs.variants(source, 'sample', arch='mips') == []


def test_closed_nested_function_still_has_liveness_facts():
    source = 'int sample(int input) { int value; value = input; if (input) { value = 2; } return value; }'
    flow = local_flow.analyze(source, 'sample')
    assert flow is not None and flow.nodes and 'value' in flow.names
    assert branch_call_support.facts(source, 'sample', arch='mips') is not None


def test_a_block_scoped_struct_tag_keeps_liveness_and_the_phase_split():
    # m2c copies a vector with a block-scoped `struct Vec { ... };` beside the copy; the tag declares no variable
    # and used to make every CFG family give up on the whole function (an N64 draft with a reused counter name)
    source = '''void f(s32 *a, s32 *b) {
    s32 n;
    s32 k;
    n = 0;
    do {
        {
            struct Vec { s32 x, y, z; };
            *(struct Vec *)a = *(struct Vec *)b;
        }
        n += 1;
    } while (n < 4);
    k = 0;
    do {
        n = g(k);
        h(n);
        h(n);
        k += 1;
    } while (k < 4);
}
'''
    from decomprepair import phase_lifetime_repairs
    assert local_flow.analyze(source, 'f') is not None
    split = phase_lifetime_repairs.splits(source, 'f')
    assert any('__repair_phase_n = g(k);' in text and 'n = 0;' in text for text in split)


def test_float_and_pointer_locals_get_their_phases_split():
    # gap: split_integer_phase only split integer locals; m2c reuses float temporaries and cursor pointers too
    from decomprepair import phase_lifetime_repairs
    source = '''void f(f32 *a, s32 *b, f32 x) {
    f32 t;
    s32 *p;
    t = x * 2.0f;
    a[0] = t;
    t = a[1] * x;
    a[2] = t;
    a[3] = t;
    p = b;
    *p = 1;
    p = b + 4;
    *p = 2;
    *p = 3;
}
'''
    split = phase_lifetime_repairs.splits(source, 'f')
    assert any('f32 __repair_phase_t;' in text and '__repair_phase_t = a[1] * x;' in text
               and 't = x * 2.0f;' in text for text in split)
    assert any('s32 *__repair_phase_p;' in text and '__repair_phase_p = b + 4;' in text for text in split)


GLOBAL_VOLATILE = '''extern volatile s32 gStatus;
s32 f(s32 a) {
    s32 v;
    v = a + 1;
    if (gStatus != 0) {
        v = a + 2;
    }
    return v;
}
'''

CAST_VOLATILE = '''extern s32 gStatus;
s32 f(s32 a) {
    s32 v;
    v = a + 1;
    if (*(volatile s32 *)&gStatus != 0) {
        v = a + 2;
    }
    return v;
}
'''


@pytest.mark.parametrize('source', [GLOBAL_VOLATILE, CAST_VOLATILE])
def test_a_volatile_global_or_a_volatile_cast_of_one_keeps_liveness(source):
    # the saved best of a game's save-state function read two status words through `(volatile T *)` casts; any
    # `volatile` in the text used to give no flow, so none of the families built on it proposed anything
    flow = local_flow.analyze(source, 'f')
    assert flow is not None and 'v' in flow.names


def test_a_volatile_local_still_gives_no_liveness():
    source = '''s32 f(s32 a) {
    volatile s32 v;
    v = a;
    return v;
}
'''
    assert local_flow.analyze(source, 'f') is None
    unusual = '''s32 f(s32 a) {
    s32 v;
    v = a;
    return (s32)(const volatile s32 *)v;
}
'''
    assert local_flow.analyze(unusual, 'f') is None


def test_float_and_pointer_phase_splits_survive_a_second_call_on_the_same_text():
    # The flow is cached per text and hands back the first call's declaration objects: splits() matched the wide
    # locals by identity, so the second call on one source returned nothing.
    from decomprepair import phase_lifetime_repairs
    source = '''void f(s32 *b) {
    s32 *p;
    p = b;
    *p = 1;
    p = b + 4;
    *p = 2;
    *p = 3;
}
'''
    first = phase_lifetime_repairs.splits(source, 'f')
    assert first and phase_lifetime_repairs.splits(source, 'f') == first
