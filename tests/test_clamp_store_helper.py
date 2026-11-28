from decomprepair import clamp_store_helper as m
from decomprepair import registry

PAD = '''typedef struct { s32 *p[4][2]; } AxisTable;
extern AxisTable D_TABLE;
extern Pad **D_PADS;

void f(s32 n) {
    AxisTable axes = D_TABLE;
    s32 i;

    for (i = 0; i < n; i++) {
        s32 x;
        s32 v;
        s32 *dst;

        x = D_PADS[i]->stick_x;
        dst = axes.p[i][0];
        if (x > 50) {
            v = x - 50;
        } else {
            v = 0;
            if (x < -50) {
                v = x + 50;
            }
        }
        *dst = v;
        x = D_PADS[i]->stick_y;
        dst = axes.p[i][1];
        if (x > 50) {
            v = x - 50;
        } else {
            v = 0;
            if (x < -50) {
                v = x + 50;
            }
        }
        *dst = v;
    }
}
'''


def children(source, family):
    return [text for kind, text in m.variants(source, 'f') if kind == family]


def test_repeated_runs_become_one_helper_that_takes_the_destination():
    [child] = children(PAD, m.HELPER)
    assert child.count('static __inline__ void f_clampStore(s32 *out, s32 x) {') == 1
    assert 'f_clampStore(axes.p[i][0], D_PADS[i]->stick_x);' in child
    assert 'f_clampStore(axes.p[i][1], D_PADS[i]->stick_y);' in child
    body = child[child.index('void f(s32 n)'):]
    assert 's32 x;' not in body and 's32 v;' not in body and 'dst' not in body


def test_the_flat_table_comes_alone_and_with_the_helper():
    [flat] = children(PAD, m.FLAT)
    assert 's32 *p[8];' in flat and 'axes.p[i * 2];' in flat and 'axes.p[i * 2 + 1];' in flat
    [both] = children(PAD, m.BOTH)
    assert 'f_clampStore(axes.p[i * 2], D_PADS[i]->stick_x);' in both
    assert 'f_clampStore(axes.p[i * 2 + 1], D_PADS[i]->stick_y);' in both


def test_a_store_straight_through_a_table_takes_its_type_from_the_declaration():
    source = PAD
    for axis in ('0', '1'):
        source = source.replace(f'        dst = axes.p[i][{axis}];\n', '')
        source = source.replace('        *dst = v;\n', f'        *axes.p[i][{axis}] = v;\n', 1)
    source = source.replace('        s32 *dst;\n', '')
    [child] = children(source, m.HELPER)
    assert 'f_clampStore(axes.p[i][1], D_PADS[i]->stick_y);' in child
    assert 's32 *out' in child


def test_a_result_read_after_the_run_stays():
    source = PAD.replace('        *dst = v;\n    }\n}', '        *dst = v;\n        use(v);\n    }\n}')
    assert not children(source, m.HELPER)


def test_branches_that_read_two_values_are_left_alone():
    assert not children(PAD.replace('v = x - 50;', 'v = x - i;'), m.HELPER)


def test_a_column_that_is_not_a_literal_stays_two_dimensional():
    assert not children(PAD.replace('axes.p[i][1]', 'axes.p[i][n]'), m.FLAT)


def test_declared_to_the_registry():
    assert 'clamp_store_helper' in {repair.module for repair in registry.declared()}
