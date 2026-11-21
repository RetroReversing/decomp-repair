from decomprepair import measured_stack_drafts

DRAFT = '''
s32 __osPfsRWInode(void *, u16 (*)[], M2C_UNK, s32);
s32 rebuild_map(void *disk, void *cache) {
    void *clear_at;
    s32 left;
    s32 count;
    s32 bank;
    s32 start;
    s32 code;
    s32 result;
    s32 index;
    u16 *entry;
    u16 raw;
    s32 word;
    u32 owner;
    void *address;
    left = 0xFF;
    clear_at = cache + 0xFF;
    do {
        M2C_FIELD(clear_at, s8 *, 0x101) = 0;
        left -= 1;
        clear_at -= 1;
    } while (left >= 0);
    M2C_FIELD(cache, s8 *, 0x100) = 0xFF;
    count = 0;
    if (M2C_FIELD(disk, u8 *, 0x64) != 0) {
        bank = 0 & 0xFF;
read:
        start = 1;
        if (bank == 0) { start = M2C_FIELD(disk, s32 *, 0x60); }
        code = __osPfsRWInode(disk, (u16 (*)[]) &sp10[0], 0, bank);
        result = code;
        if (!((code != 0) & (code != 3))) {
            index = start;
            if (index < 0x80) {
                entry = &(&sp10[0])[index];
                do {
                    raw = *entry;
                    word = raw & 0xFFFF;
                    index += 1;
                    if (word >= M2C_FIELD(disk, s32 *, 0x60)) {
                        owner = (u32) word >> 8;
                        if (owner != bank) {
                            address = cache + (((u32) (raw & 0xFF) >> 2) + ((owner & 7) << 5));
                            M2C_FIELD(address, u8 *, 0x101) = (u8) (M2C_FIELD(address, u8 *, 0x101) | (1 << (bank & 7)));
                        }
                    }
                    entry += 2;
                } while (index < 0x80);
            }
            count += 1;
            bank = count & 0xFF;
            if ((u32) (count & 0xFF) >= (u8) M2C_FIELD(disk, u8 *, 0x64)) { goto done; }
            goto read;
        }
    } else {
done:
        result = 0;
    }
    return result;
}
'''
ASM = '''
addiu $sp, $sp, -304
sw $s0, 272($sp)
sb $zero, 257($v0)
sb $v0, 256($s4)
lbu $v0, 100($s2)
addiu $s5, $sp, 16
andi $s0, $s3, 255
lw $s1, 96($s2)
addiu $a1, $sp, 16
jal __osPfsRWInode
slti $v0, $a1, 128
sllv $t0, $s6, $v0
lhu $a0, 0($a2)
srl $v1, $v1, 8
srl $v0, $v0, 2
sll $v1, $v1, 5
lbu $v1, 257($v0)
sb $v1, 257($v0)
slti $v0, $a1, 128
addiu $a2, $a2, 2
'''


def test_inode_cache_recovers_typed_page_and_map():
    assert measured_stack_drafts.applies(ASM)
    fixed = measured_stack_drafts.rewrite(DRAFT, 'rebuild_map', ASM)
    assert '__m2c_copy_entry_t __m2c_copy_page[128];' in fixed
    assert 'unsigned char map[256];' in fixed
    assert 'cache->map[__m2c_copy_slot] |= 1 << (__m2c_copy_bank % 8);' in fixed
    assert 'sp10' not in fixed


def test_inode_cache_refuses_conflicting_target_and_declared_callee():
    changed_stride = ASM.replace('addiu $a2, $a2, 2', 'addiu $a2, $a2, 4')
    assert not measured_stack_drafts.applies(changed_stride)
    assert not measured_stack_drafts.rewrite(DRAFT, 'rebuild_map', changed_stride)
    assert not measured_stack_drafts.rewrite(DRAFT, 'rebuild_map', ASM, 'int __osPfsRWInode();')
