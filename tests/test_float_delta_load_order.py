from decomprepair.float_delta_load_order import FAMILY, variants

SOURCE = """
void adjust(char *record)
{
    f32 old;
    f32 delta;
    old = *((f32 *) (((char *) record) + 8));
    delta = ((*((f32 *) (((char *) record) + 12))) - old) * 0.25f;
    use(delta);
}
"""

ROWS = [
    ('i', 'lwc1 $f0, 12($s1)', 'lwc1 $f2, 8($s1)'),
    ('i', 'lwc1 $f2, 8($s1)', 'lwc1 $f0, 12($s1)'),
    (' ', 'sub.s $f0, $f0, $f2', 'sub.s $f0, $f0, $f2'),
]


def test_stages_the_minuend_load_and_keeps_arithmetic():
    [(family, revised)] = variants(SOURCE, 'adjust', ROWS)
    assert family == FAMILY
    assert revised.index('repair_delta_input =') < revised.index('old =')
    assert 'delta = ((repair_delta_input) - old) * 0.25f;' in revised
    assert variants(revised, 'adjust', ROWS) == []


def test_requires_exact_measured_swap_and_ordinary_loads():
    assert variants(SOURCE.replace('+ 12', '+ 16'), 'adjust', ROWS) == []
    assert variants(SOURCE, 'adjust', ROWS, header='typedef volatile float f32;') == []
    assert variants(SOURCE, 'adjust', [(' ', a, a) for _, a, _ in ROWS]) == []
    assert variants(SOURCE, 'adjust', ROWS[:2] + [(' ', 'add.s $f0, $f0, $f2', 'add.s $f0, $f0, $f2')]) == []
