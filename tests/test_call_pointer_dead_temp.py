"""An indirect call's pointer loaded into a dead integer temp, after the temp's last read."""
from decomprepair import call_pointer_dead_temp as p
from decomprepair import registry

SOURCE = '''typedef unsigned int u32;
typedef int s32;
extern s32 (*gAlloc)(s32, s32, s32);
extern s32 gBuffer;
extern s32 gSize;

void setup(u32 *rate, s32 ms)
{
    s32 temp_v0;
    s32 temp_a2;
    s32 var_v0;
    u32 s;
    temp_v0 = *rate;
    temp_a2 = ms & 0xFFFF;
    if (temp_a2 != 0) {
        temp_a2 = ((u32) temp_v0 * temp_a2) / 1000;
        temp_v0 = (u32) temp_a2 / 192;
        var_v0 = temp_v0 * 192;
        s = var_v0 + 192;
        gSize = s;
        gBuffer = gAlloc(s * 2, 0, s);
    } else {
        gBuffer = 0;
    }
    var_v0 = 0;
    gSize += var_v0;
}
'''

CALL = 'gBuffer = ((s32 (*)(s32, s32, s32)) temp_v0)(s * 2, 0, s);'


def texts(source, header=''):
    return [text for _, text in p.variants(source, 'setup', header)]


def test_the_judged_shape_is_reached():
    """The audio setup step (255 -> 0): the pointer loaded into the dead quotient temp right after its last read."""
    expected = SOURCE.replace('var_v0 = temp_v0 * 192;', 'var_v0 = temp_v0 * 192; temp_v0 = (s32) gAlloc;').replace(
        'gBuffer = gAlloc(s * 2, 0, s);', CALL)
    assert expected in texts(SOURCE)


def test_a_temp_read_between_the_insertion_and_the_call_is_not_used():
    for text in texts(SOURCE):
        assert 's = (u32) gAlloc;' not in text


def test_a_temp_read_after_the_call_is_not_used():
    assert not any('temp_a2 = (s32) gAlloc;' in text for text in
                   texts(SOURCE.replace('gSize += var_v0;', 'gSize += var_v0 + temp_a2;')))


def test_never_between_an_arm_and_its_else():
    for text in texts(SOURCE):
        assert '} temp' not in text and '}temp' not in text


def test_the_pointer_may_be_declared_in_the_header():
    source = SOURCE.replace('extern s32 (*gAlloc)(s32, s32, s32);\n', '')
    assert texts(source) == []
    assert any(CALL in text for text in texts(source, 'extern s32 (*gAlloc)(s32, s32, s32);'))


def test_a_direct_call_is_left_alone():
    source = SOURCE.replace('extern s32 (*gAlloc)(s32, s32, s32);', 'extern s32 gAlloc(s32, s32, s32);')
    assert texts(source) == []


def test_it_declares_itself():
    repair = registry.get('call_pointer_dead_temp')
    assert repair is not None and not registry.problems(repair)
    assert 'call_pointer_dead_temp' in repair.families
