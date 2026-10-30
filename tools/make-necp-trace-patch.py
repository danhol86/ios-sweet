#!/usr/bin/env python3
"""Generate opt-in NECP path trace patch against the pinned iOS XNU baseline."""
from pathlib import Path
import difflib
base=Path('/home/ios-sweet-test/ci-buildtree-0082/xnu/bsd/net/necp_client.c')
assert base.is_file(), 'Expected local saved XNU baseline'
original=base.read_text()
s=original
assert '#include <kern/zalloc.h>\n' in s
s=s.replace('#include <kern/zalloc.h>\n','#include <kern/zalloc.h>\n#include <kern/startup.h>\n',1)
a='#include <os/refcnt.h>\n'
assert s.count(a)==1
helper='''
#if defined(ARM64_BOARD_CONFIG_SWEET)
/* QEMU-only diagnostics. No network permissions or policies are changed. */
static TUNABLE(uint32_t, sweet_qemu_necp_trace, "sweet_qemu_necp_trace", 0);
static uint32_t sweet_necp_browser_count;
static uint32_t sweet_necp_daemon_count;
static void
sweet_necp_path_trace(struct proc *p, const char *action, uint32_t kind, int result)
{
    if (!sweet_qemu_necp_trace || !p) return;
    char name[32] = { 0 };
    proc_name(proc_pid(p), name, sizeof(name));
    /* XNU proc_name can be truncated to MAXCOMLEN; do not require a complete
       com.apple.WebKit.Networking process name. */
    int browser = strcmp(name, "MobileSafari") == 0 ||
        strncmp(name, "com.apple.Web", 13) == 0;
    int daemon = strcmp(name, "networkd") == 0 ||
        strcmp(name, "configd") == 0;
    if (browser) {
        if (sweet_necp_browser_count++ >= 120) return;
    } else if (daemon) {
        if (sweet_necp_daemon_count++ >= 24) return;
    } else return;
    printf("SWEET NECP: %s %s kind=%u error=%d\\n",
        name, action, kind, result);
}
#endif /* ARM64_BOARD_CONFIG_SWEET */
'''
s=s.replace(a,a+helper,1)
# Entry/exit of the kernel path-resolution APIs; avoids logging addresses or tokens.
anchor='int\nnecp_open(struct proc *p, struct necp_open_args *uap, int *retval)\n{\n'
assert s.count(anchor)==1
s=s.replace(anchor,anchor+'#if defined(ARM64_BOARD_CONFIG_SWEET)\n    sweet_necp_path_trace(p, "open", uap->flags, 0);\n#endif\n',1)
anchor='''\treturn error;
}

// All functions called directly from necp_client_action()'''
assert s.count(anchor)==1
s=s.replace(anchor,'''#if defined(ARM64_BOARD_CONFIG_SWEET)
    sweet_necp_path_trace(p, "open-result", uap->flags, error);
#endif
''' + anchor,1)
anchor='''int
necp_client_action(struct proc *p, struct necp_client_action_args *uap, int *retval)
{
'''
assert s.count(anchor)==1
s=s.replace(anchor,anchor+'#if defined(ARM64_BOARD_CONFIG_SWEET)\n    sweet_necp_path_trace(p, "client-action", uap->action, 0);\n#endif\n',1)
anchor='''done:
\tfp_drop(p, uap->necp_fd, fp, 0);
\treturn return_value;
}

#define NECP_MAX_MATCH_POLICY_PARAMETER_SIZE'''
assert s.count(anchor)==1
s=s.replace(anchor,'''done:
    fp_drop(p, uap->necp_fd, fp, 0);
#if defined(ARM64_BOARD_CONFIG_SWEET)
    sweet_necp_path_trace(p, "client-result", uap->action, return_value);
#endif
    return return_value;
}

#define NECP_MAX_MATCH_POLICY_PARAMETER_SIZE''',1)
anchor='''int
necp_match_policy(struct proc *p, struct necp_match_policy_args *uap, int32_t *retval)
{
'''
assert s.count(anchor)==1
s=s.replace(anchor,anchor+'#if defined(ARM64_BOARD_CONFIG_SWEET)\n    sweet_necp_path_trace(p, "match-policy", 0, 0);\n#endif\n',1)
assert s!=original
name='bsd/net/necp_client.c'
patch='diff --git a/'+name+' b/'+name+'\n'+''.join(difflib.unified_diff(original.splitlines(keepends=True),s.splitlines(keepends=True),fromfile='a/'+name,tofile='b/'+name,n=4))
output=Path('/mnt/d/Projects/ios-sweet-net-ioreg-probe/xnu/patches/0094-sweet-qemu-necp-path-trace.patch')
output.write_text(patch,newline='\n')
print('WROTE',output,'BYTES',output.stat().st_size)
