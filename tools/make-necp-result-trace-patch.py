#!/usr/bin/env python3
"""Generate opt-in QEMU NECP route-result tracer from locally validated 0094 XNU."""
from pathlib import Path
import difflib
base=Path('/home/ios-sweet-test/ci-buildtree-0082/xnu/bsd/net/necp_client.c')
orig=base.read_text()
assert 'sweet_necp_path_trace' in orig, 'Requires 0094 patch first'
mark='''#endif /* ARM64_BOARD_CONFIG_SWEET */
'''
assert orig.count(mark)==1
helper='''
#if defined(ARM64_BOARD_CONFIG_SWEET)
static uint32_t sweet_necp_result_count;
/* Only predefined, non-sensitive flags and index from each client result. */
static uint32_t
sweet_necp_u32_tlv(uint8_t *result, uint32_t len, uint8_t type)
{
    int off = necp_buffer_find_tlv(result, len, 0, type, NULL, FALSE);
    if (off < 0) return 0;
    uint32_t size = 0;
    uint8_t *v = necp_buffer_get_tlv_value(result, off, &size);
    uint32_t out = 0;
    if (v && size == sizeof(out)) memcpy(&out, v, sizeof(out));
    return out;
}
static void
sweet_necp_result_trace(pid_t pid, uint8_t *result, size_t len)
{
    if (!sweet_qemu_necp_trace || !result || !len ||
        sweet_necp_result_count >= 90) return;
    char name[32] = { 0 };
    proc_name(pid, name, sizeof(name));
    if (strcmp(name, "MobileSafari") != 0 &&
        strncmp(name, "com.apple.Web", 13) != 0) return;
    sweet_necp_result_count++;
    uint32_t size = (uint32_t)len;
    printf("SWEET NECP RESULT: %s flags=0x%x policy=%u ifindex=%u reason=%u\\n",
        name,
        sweet_necp_u32_tlv(result, size, NECP_CLIENT_RESULT_FLAGS),
        sweet_necp_u32_tlv(result, size, NECP_CLIENT_RESULT_POLICY_RESULT),
        sweet_necp_u32_tlv(result, size, NECP_CLIENT_RESULT_INTERFACE_INDEX),
        sweet_necp_u32_tlv(result, size, NECP_CLIENT_RESULT_REASON));
}
#endif /* ARM64_BOARD_CONFIG_SWEET */
'''
s=orig.replace(mark,mark+helper,1)
needle='''\t\terror = copyout(client->result, uap->buffer, client->result_length);
'''
assert s.count(needle)==1
s=s.replace(needle,'''#if defined(ARM64_BOARD_CONFIG_SWEET)
        sweet_necp_result_trace(client->proc_pid, client->result, client->result_length);
#endif
''' + needle,1)
name='bsd/net/necp_client.c'
patch='diff --git a/'+name+' b/'+name+'\n'+''.join(difflib.unified_diff(orig.splitlines(keepends=True),s.splitlines(keepends=True),fromfile='a/'+name,tofile='b/'+name,n=4))
p=Path('/mnt/d/Projects/ios-sweet-net-ioreg-probe/xnu/patches/0095-sweet-qemu-necp-result-trace.patch')
p.write_text(patch,newline='\n')
print('PATCH',p,'BYTES',p.stat().st_size)
