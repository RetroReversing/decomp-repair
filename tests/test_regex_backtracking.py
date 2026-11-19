"""A long run of simple statements must not make a family's statement-run pattern backtrack exponentially (a deep
pass spent 2.75 hours in one function's signed-division forms)."""
import time

from decomprepair import goto_loop_repairs, search_loop_repairs, short_counter_loop_repairs, signed_division_repairs

BODY = ''.join(f'    a{i} = b{i} + c{i};   \n' for i in range(40))
SOURCE = 'void f(int x) {\n    int v;\n    v = x;\n' + BODY + '    if (v < 0) {\n        v = y;\n    }\n' + BODY + '}\n'


def test_statement_runs_stay_fast():
    for module in (signed_division_repairs, goto_loop_repairs, search_loop_repairs, short_counter_loop_repairs):
        started = time.monotonic()
        module.variants(SOURCE, 'f')
        assert time.monotonic() - started < 2, module.__name__

