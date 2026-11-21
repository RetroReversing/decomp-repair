from decomprepair.identical_float_guard import variants

SOURCE = '''void f(f32 x) {
 f64 wide;
 wide = (f64) x;
 do { if (x) { work(); } else { work(); } } while (more());
}'''


def test_initialized_double_can_replace_pure_identical_arm_guard():
    assert any('if (wide)' in s for _, s in variants(SOURCE, 'f', arch='mips'))


def test_declines_uninitialized_or_differing_arms_and_escaped_local():
    for source in (SOURCE.replace('wide = (f64) x;', ''),
                   SOURCE.replace('wide = (f64) x;', 'if (x) { wide = (f64) x; }'),
                   SOURCE.replace('else { work(); }', 'else { other(); }'),
                   SOURCE.replace('wide = (f64) x;', 'wide = (f64) x; use(&wide);')):
        assert variants(source, 'f', arch='mips') == []
