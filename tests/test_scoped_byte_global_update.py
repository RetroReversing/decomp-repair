import pytest

from decomprepair.global_store_repairs import scoped_byte_updates

SOURCE = 'extern u8 state; void update(void) { state -= 1; }'
ASM = """lui $v1, %hi(state)
addiu $v1, $v1, %lo(state)
lbu $v0, 0($v1)
addiu $v0, $v0, -1
sb $v0, 0($v1)"""


def test_keeps_the_global_address_local_to_the_update():
    [(family, source)] = scoped_byte_updates(SOURCE, 'update', ASM)
    assert family == 'scoped_byte_global_update'
    assert '{ u8 *__repair_byte_address = &state; *__repair_byte_address -= 1; }' in source


@pytest.mark.parametrize('source,asm', [
    (SOURCE.replace('extern u8', 'extern volatile u8'), ASM),
    (SOURCE.replace('void update(void)', 'void update(u8 state)'), ASM),
    (SOURCE.replace('state -= 1;', 'state -= 2;'), ASM),
    (SOURCE, ASM.replace('sb $v0, 0($v1)', 'sb $v0, 0($a0)')),
    (SOURCE, ASM.replace('%lo(state)', '%lo(other)')),
])
def test_requires_a_matching_global_type_operation_and_address(source, asm):
    assert scoped_byte_updates(source, 'update', asm) == []
