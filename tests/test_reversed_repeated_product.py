from decomprepair.measured_kmc_flow import variants

ROWS = [('r', 'mult $a2, $a0', 'mult $a0, $a2')]
SOURCE = '''
typedef unsigned int u32;
typedef int s32;

int f(s32 h, u32 w) {
    s32 height;
    u32 width;
    u32 count;
    height = h;
    width = w;
    count = ((u32) (height * width)) >> 1;
    if (((u32) (height * width)) >> 1) {
        return count;
    }
    return 0;
}
'''


def test_reverses_all_instances_of_the_measured_product():
    [(family, result)] = variants(SOURCE, 'f', '', ROWS)
    assert family == 'arithmetic_operand_order'
    assert result.count('width * height') == 2


def test_rejects_unwitnessed_volatile_and_unrepeated_products():
    assert not variants(SOURCE, 'f', '', [('r', 'mult $a2, $a0', 'mult $a1, $a2')])
    assert not variants(SOURCE.replace('u32 width;', 'volatile u32 width;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('count = ((u32) (height * width)) >> 1;', 'count = 0;'), 'f', '', ROWS)
