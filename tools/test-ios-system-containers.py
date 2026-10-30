#!/usr/bin/env python3
"""No-Apple-media integration test for first-boot QEMU MCM container seeding."""
import importlib.util
from pathlib import Path
import plistlib
from tempfile import TemporaryDirectory


def main():
    module_file = Path(__file__).resolve().with_name('sweet-root-tweaks.py')
    spec = importlib.util.spec_from_file_location('iossweet_root_tweaks', module_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with TemporaryDirectory(prefix='iossweet-mcm-test-') as workspace:
        root = Path(workspace)
        module.containers(str(root))
        module.seed_system_containers(str(root))
        base = root / 'private/var/containers/Data/System'
        expected = set(module.SYSTEM_CONTAINER_IDENTIFIERS)
        names = set()
        ids = set()
        for folder in base.iterdir():
            meta = folder / '.com.apple.mobile_container_manager.metadata.plist'
            assert meta.is_file(), folder
            plist = plistlib.loads(meta.read_bytes())
            names.add(plist['MCMMetadataIdentifier'])
            ids.add(plist['MCMMetadataUUID'])
            assert folder.name == plist['MCMMetadataUUID']
            assert plist['MCMMetadataContentClass'] == 12
            assert plist['MCMMetadataVersion'] == 6
            assert plist['MCMMetadataInfo']['com.apple.MobileInstallation.ContentProtectionClass'] == -1
        assert names == expected
        assert len(ids) == len(expected)
        module.activation(str(root))
        activation = module.find_container(str(root), 'Data/System',
                                           'com.apple.mobileactivationd')
        assert activation
        ark = Path(activation) / 'Library/internal/data_ark.plist'
        assert plistlib.loads(ark.read_bytes())['-ActivationState'] == 'Activated'
        module.seed_system_containers(str(root))
        assert len(list(base.iterdir())) == len(expected), 'Seed must be idempotent'
        print('IOS_SWEET_MCM_SYNTHETIC_TEST_PASSED')


if __name__ == '__main__':
    main()
