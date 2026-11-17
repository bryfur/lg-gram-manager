#!/usr/bin/python3 -I
"""Validated profile data and a fixed-purpose, non-GUI privileged helper."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

OPTIONS = {
    'battery': ('Battery limit', {'80': '80%', '100': '100%'}),
    'fan': ('Fan mode', {'0': 'Optimal', '1': 'Silent', '2': 'Performance'}),
    'fn_lock': ('Fn lock', {'0': 'Off', '1': 'On'}),
    'reader_mode': ('Reader mode', {'0': 'Off', '1': 'On'}),
    'usb_charge': ('USB charging', {'0': 'Off', '1': 'On'}),
    'keyboard': ('Keyboard light', {'0': 'Off', '127': 'Low', '255': 'High'}),
    'touchpad': ('Touchpad LED', {'0': 'Off', '1': 'On'}),
}
CONFIG = Path('/etc/lg-gram-manager/boot.json')
SERVICE = 'lg-gram-manager-boot.service'
HELPER = '/usr/libexec/lg-gram-manager-profiles'


def validate(profile):
    if not isinstance(profile, dict) or set(profile) != {'name', 'settings'}:
        raise ValueError('Invalid profile structure')
    name, settings = profile['name'], profile['settings']
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise ValueError('Profile name must contain 1-80 characters')
    if not isinstance(settings, dict) or not settings:
        raise ValueError('Select at least one setting')
    for key, value in settings.items():
        if key not in OPTIONS or not isinstance(value, str) or value not in OPTIONS[key][1]:
            raise ValueError('Unsupported setting or value')
    return {'name': name.strip(), 'settings': dict(settings)}


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2)
            stream.write('\n')
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def paths_for(key, root=Path('/sys')):
    platform = root / 'devices/platform/lg-laptop'
    if key == 'battery':
        return sorted((root / 'class/power_supply').glob('*/charge_control_end_threshold')) + [platform / 'battery_care_limit']
    if key in ('keyboard', 'touchpad'):
        names = ('kbd_backlight', 'lg_laptop::kbd_backlight') if key == 'keyboard' else ('tpad_led', 'lg_laptop::tpad')
        return [root / 'class/leds' / name / 'brightness' for name in names]
    return [platform / ('fan_mode' if key == 'fan' else key)]


def apply_profile(profile, root=Path('/sys'), timeout=30, sleep=time.sleep):
    profile = validate(profile)
    pending = dict(profile['settings'])
    results = {}
    deadline = time.monotonic() + timeout
    while pending:
        for key, value in list(pending.items()):
            errors = []
            for path in paths_for(key, root):
                if not path.exists():
                    continue
                try:
                    path.write_text(value + '\n')
                    if path.read_text().strip() != value:
                        raise OSError('readback differs from requested value')
                    results[key] = 'applied'
                    del pending[key]
                    break
                except OSError as exc:
                    errors.append(str(exc))
            if key in pending:
                results[key] = '; '.join(errors) if errors else 'unsupported or interface unavailable'
        if not pending or time.monotonic() >= deadline:
            break
        sleep(min(1, max(0, deadline - time.monotonic())))
    return results


def main():
    if os.geteuid() != 0:
        raise PermissionError('Administrator authorization required')
    if len(sys.argv) != 2 or sys.argv[1] not in ('enable', 'disable', 'apply', 'apply-now'):
        raise ValueError('Expected enable, disable, apply, or apply-now')
    action = sys.argv[1]
    if action in ('enable', 'apply-now'):
        raw = sys.stdin.read(16385)
        if len(raw) > 16384:
            raise ValueError('Profile too large')
        profile = validate(json.loads(raw))
    if action == 'enable':
        old = CONFIG.read_bytes() if CONFIG.exists() else None
        atomic_json(CONFIG, profile)
        try:
            subprocess.run(['/usr/bin/systemctl', 'enable', SERVICE], check=True)
        except subprocess.CalledProcessError:
            if old is None:
                CONFIG.unlink(missing_ok=True)
            else:
                atomic_json(CONFIG, json.loads(old))
            raise
    elif action == 'disable':
        subprocess.run(['/usr/bin/systemctl', 'disable', SERVICE], check=True)
        CONFIG.unlink(missing_ok=True)
    else:
        if action == 'apply':
            profile = validate(json.loads(CONFIG.read_text()))
        results = apply_profile(profile)
        for key, result in results.items():
            print(f'{key}: {result}', flush=True)
        return 0 if all(result == 'applied' for result in results.values()) else 1
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
