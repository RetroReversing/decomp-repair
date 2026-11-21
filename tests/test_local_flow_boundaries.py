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
