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


def test_nested_guard_reuses_an_initialized_float_and_declines_uninitialized():
    source = '''void f(f32 x) {
 f64 wide; f32 scale;
 wide = (f64) x; scale = x * 0.2f;
 do { if (wide) { work(scale); } else { work(scale); } } while (more());
}'''
    choices = variants(source, 'f', arch='mips')
    assert any(family == 'initialized_nested_float_guard' and 'if (scale)' in text for family, text in choices)
    assert not variants(source.replace('scale = x * 0.2f;', ''), 'f', arch='mips')
    assert not variants(source.replace('f32 scale;', 'volatile f32 scale;'), 'f', arch='mips')
    assert not variants(source.replace('work(scale);', 'goto out;') + '\nout:', 'f', arch='mips')
