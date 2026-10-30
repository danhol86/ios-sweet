#!/usr/bin/env python3
"""Local syntax/object check with existing XNU CI build flags, no game/phone access."""
import importlib.util,os,sys
spec=importlib.util.spec_from_file_location('xnu_cc','/mnt/d/Projects/ios-sweet/tools/xnu-cc.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.CLANG='/home/ios-sweet-test/inspection/clangbin/clang'
os.environ['XNU_CC_OBJDIR']='/home/ios-sweet-test/inspection/necp-path-trace-objects'
os.makedirs(os.environ['XNU_CC_OBJDIR'],exist_ok=True)
sys.argv=['xnu-cc.py','/home/ios-sweet-test/inspection/ci-0086-build-utf8.log',
          '/home/ios-sweet-test/ci-buildtree-0082','necp_client.c','--per-file']
sys.exit(m.main())
