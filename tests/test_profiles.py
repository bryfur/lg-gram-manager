import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import lg_gram_profiles as profiles


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def profile(self, **settings):
        return {'name': 'Default', 'settings': settings}

    def interface(self, relative, value='100'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def test_validation_rejects_invalid_input(self):
        for item in ({}, [], self.profile(), self.profile(battery='70'),
                     self.profile(battery=80), self.profile(command='rm')):
            with self.subTest(item=item), self.assertRaises(ValueError):
                profiles.validate(item)

    def test_dynamic_battery_and_idempotency(self):
        path = self.interface('class/power_supply/BAT0/charge_control_end_threshold')
        for _ in range(2):
            self.assertEqual(profiles.apply_profile(self.profile(battery='80'), self.root, 0), {'battery': 'applied'})
            self.assertEqual(path.read_text().strip(), '80')

    def test_legacy_fallback(self):
        path = self.interface('devices/platform/lg-laptop/battery_care_limit')
        self.assertEqual(profiles.apply_profile(self.profile(battery='80'), self.root, 0)['battery'], 'applied')
        self.assertEqual(path.read_text().strip(), '80')

    def test_unmanaged_setting_not_written(self):
        fan = self.interface('devices/platform/lg-laptop/fan_mode', '0')
        profiles.apply_profile(self.profile(battery='80'), self.root, 0)
        self.assertEqual(fan.read_text(), '0')

    def test_missing_control_does_not_block_other_controls(self):
        self.interface('devices/platform/lg-laptop/fan_mode', '0')
        results = profiles.apply_profile(self.profile(battery='80', fan='1'), self.root, 0)
        self.assertEqual(results['fan'], 'applied')
        self.assertIn('unavailable', results['battery'])

    def test_late_interface(self):
        def sleep(_):
            self.interface('class/power_supply/CMB0/charge_control_end_threshold')
        self.assertEqual(profiles.apply_profile(self.profile(battery='80'), self.root, 2, sleep)['battery'], 'applied')

    def test_readback_failure(self):
        self.interface('devices/platform/lg-laptop/fan_mode', '0')
        with patch.object(Path, 'read_text', return_value='0'):
            results = profiles.apply_profile(self.profile(fan='1'), self.root, 0)
        self.assertIn('readback', results['fan'])

    def test_save_is_separate_from_boot_copy(self):
        local, boot = self.root / 'local.json', self.root / 'boot.json'
        profiles.atomic_json(boot, self.profile(battery='80'))
        profiles.atomic_json(local, self.profile(battery='100'))
        self.assertEqual(json.loads(boot.read_text())['settings']['battery'], '80')

    def test_authorization_required(self):
        with patch('os.geteuid', return_value=1000), self.assertRaises(PermissionError):
            profiles.main()

    def invoke(self, action, profile=None):
        with patch('os.geteuid', return_value=0), patch('sys.argv', ['helper', action]), patch('sys.stdin', io.StringIO(json.dumps(profile))):
            return profiles.main()

    def test_enable_does_not_apply_and_disable_removes_copy(self):
        config = self.root / 'etc/boot.json'
        with patch.object(profiles, 'CONFIG', config), patch('subprocess.run') as run, patch.object(profiles, 'apply_profile') as apply:
            self.invoke('enable', self.profile(battery='80'))
            self.assertEqual(json.loads(config.read_text())['settings']['battery'], '80')
            apply.assert_not_called()
            self.assertEqual(run.call_args.args[0], ['/usr/bin/systemctl', 'enable', profiles.SERVICE])
            self.invoke('disable')
            self.assertFalse(config.exists())

    def test_enable_failure_restores_previous_copy(self):
        import subprocess
        config = self.root / 'etc/boot.json'
        profiles.atomic_json(config, self.profile(battery='100'))
        with patch.object(profiles, 'CONFIG', config), patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'systemctl')):
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke('enable', self.profile(battery='80'))
        self.assertEqual(json.loads(config.read_text())['settings']['battery'], '100')


if __name__ == '__main__':
    unittest.main()
