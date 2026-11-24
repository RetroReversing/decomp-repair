"""A run of scalar updates at a loop body's end wrapped in one-shot scopes."""
from decomprepair import registry
from decomprepair.update_run_scope import FAMILY, variants

MIDDLE = '''void f(u32 *H, u32 tb) {
    u32 c;
    u32 off = 4;
    u32 *q3 = H + 1;
    c = 1;
    do {
        H[c] = off;
        off += 4;
        c++;
        q3++;
    } while (c < tb);
}
'''


def test_the_middle_loops_run_is_wrapped_whole():
    # a 681-instruction N64 decoder: `do { off += 4; c++; q3++; } while (0);` matched its middle loop's registers
    kids = [text for _, text in variants(MIDDLE, 'f')]
    assert any('do { off += 4;\n        c++;\n        q3++; } while (0);' in k for k in kids)


def test_a_constant_step_is_wrapped_three_deep():
    # and `off += 4` alone, three deep, its search loop's offset
    text = MIDDLE.replace('        c++;\n        q3++;\n', '').replace('off += 4;', 'c++;\n        off += 4;')
    kids = [k for _, k in variants(text, 'f')]
    assert any('do { do { do { off += 4; } while (0); } while (0); } while (0);' in k for k in kids)


def test_a_lone_plain_increment_is_left_to_loop_weight_scope():
    text = MIDDLE.replace('        off += 4;\n        c++;\n        q3++;\n', '        c++;\n')
    assert variants(text, 'f') == []


def test_an_address_taken_local_stays():
    text = MIDDLE.replace('H[c] = off;', 'H[c] = off; g(&off);')
    assert not any('do { off += 4' in k for _, k in variants(text, 'f'))


def test_every_child_is_the_family():
    assert {family for family, _ in variants(MIDDLE, 'f')} == {FAMILY}


def test_the_module_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'update_run_scope')
    assert registry.problems(repair) == [] and FAMILY in repair.families
