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
