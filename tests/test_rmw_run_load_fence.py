"""rmw_run_load_fence: three byte updates, one value read early and the next read inside a one-shot scope (60 -> 0)."""
from decomprepair import rmw_run_load_fence as f

SOURCE = '''void func_80016A84(void *arg0) {
    u8 temp_copy;

    if (M2C_FIELD(arg0, u8 *, 0x86) >= 3U) {
        M2C_FIELD(arg0, u8 *, 0x72) = (u8) (M2C_FIELD(arg0, u8 *, 0x72) - 0x32);
        temp_copy = M2C_FIELD(arg0, u8 *, 0x73);
        do { M2C_FIELD(arg0, u8 *, 0x71) = (u8) (M2C_FIELD(arg0, u8 *, 0x71) - 0x32); } while (0);
        M2C_FIELD(arg0, u8 *, 0x73) = (u8) (temp_copy - 0x32);
    }
}
'''
R, G, B = (f'M2C_FIELD(arg0, u8 *, 0x{o})' for o in ('71', '72', '73'))
EXACT = f'''rmw_early = {B};
        {R} -= 0x32;
        do {{
            rmw_late = {G};
            {B} = (u8) (rmw_early - 0x32);
        }} while (0);
        {G} = (u8) (rmw_late - 0x32);
    }}'''


def _texts(source, name='func_80016A84', header=''):
    out = f.variants(source, name, header)
    assert all(family == f.FAMILY for family, _ in out)
    return [text for _, text in out]


def test_the_saved_shape_reaches_the_exact_order():
    texts = _texts(SOURCE)
    assert len(texts) == 6
    exact = [text for text in texts if EXACT in text]
    assert len(exact) == 1
    assert 'u8 rmw_early;\n    u8 rmw_late;' in exact[0]
    assert exact[0].count('{') == exact[0].count('}')


def test_plain_compound_updates_and_bare_blocks():
    plain = SOURCE[:SOURCE.index('        M2C_FIELD(arg0, u8 *, 0x72)')]
    compound = plain + f'        {R} -= 0x32;\n        {G} -= 0x32;\n        {B} -= 0x32;\n    }}\n}}\n'
    assert any(EXACT in text for text in _texts(compound))
    block = SOURCE.replace('do { ', '{ ').replace(' } while (0);', ' }')
    assert any(EXACT in text for text in _texts(block))


def test_casted_dereferences_and_globals():
    wrapped = SOURCE
    for off in ('71', '72', '73'):
        wrapped = wrapped.replace(f'M2C_FIELD(arg0, u8 *, 0x{off})', f'(*(u8 *)((char *)(arg0) + 0x{off}))')
    assert len(_texts(wrapped)) == 6
    globals_ = 'extern u8 gR;\nextern u8 gG;\nextern u8 gB;\nvoid fade(void) {\n    gR -= 1;\n    gG -= 1;\n    gB -= 1;\n}\n'
    assert len(_texts(globals_, 'fade')) == 6


def test_shapes_it_leaves_alone():
    assert _texts(SOURCE.replace('0x73)', '0x72)')) == []  # two updates of one byte
    assert _texts(SOURCE.replace('u8 *, 0x71', 'u16 *, 0x71')) == []  # overlapping
    assert _texts(SOURCE.replace('    }\n}', '        use(temp_copy);\n    }\n}')) == []  # the temporary is read again
    assert _texts(SOURCE.replace('u8 *, 0x', 'volatile u8 *, 0x')) == []
    assert _texts(SOURCE.replace('do {', 'if (x) {').replace('} while (0);', '}')) == []
    assert _texts(SOURCE, 'missing') == []


def test_the_module_declares_itself_for_the_registry():
    assert f.REPAIR['variants'] is f.variants and f.REPAIR['families'] == f.FAMILIES
    assert f.REPAIR['needs'] == ('source', 'name', 'header')
