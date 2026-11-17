"""Profile editor; privileged operations are delegated to the installed helper."""

import json
import os
from pathlib import Path
import subprocess
import threading

from gi.repository import Gtk, GLib
from lg_gram_profiles import CONFIG, HELPER, OPTIONS, atomic_json, validate


class ProfileWindow(Gtk.Window):
    def __init__(self, parent):
        super().__init__(title='Profiles', transient_for=parent, modal=True)
        self.set_default_size(480, 650)
        self.path = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'lg-gram-manager/profiles.json'
        self.profiles = {}
        self.load_error = None
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if not isinstance(data, list):
                    raise ValueError('Expected a list of profiles')
                for item in data:
                    item = validate(item)
                    if item['name'] in self.profiles:
                        raise ValueError('Duplicate profile name')
                    self.profiles[item['name']] = item
            except (ValueError, OSError) as exc:
                self.load_error = str(exc)
        else:
            self.profiles['Default'] = {'name': 'Default', 'settings': {'battery': '80', 'fan': '0'}}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, 'set_margin_' + side)(16)
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(box)
        self.set_child(scroll)
        self.selector = Gtk.DropDown()
        self.selector.connect('notify::selected', self.load_selected)
        box.append(self.selector)
        self.name = Gtk.Entry(placeholder_text='Profile name')
        box.append(self.name)
        self.controls = {}
        for key, (title, values) in OPTIONS.items():
            row = Gtk.Box(spacing=12)
            label = Gtk.Label(label=title, xalign=0, hexpand=True)
            choices = ['Unmanaged'] + list(values.values())
            control = Gtk.DropDown.new_from_strings(choices)
            self.controls[key] = control
            row.append(label)
            row.append(control)
            box.append(row)
        self.buttons = []
        for actions in (
            [('document-new-symbolic', 'New', self.new), ('document-save-symbolic', 'Save', self.save),
             ('document-edit-symbolic', 'Rename', self.rename), ('user-trash-symbolic', 'Delete', self.delete)],
            [('media-playback-start-symbolic', 'Apply now', lambda *_: self.run('apply-now')),
             ('system-run-symbolic', 'Use at boot', lambda *_: self.run('enable')),
             ('process-stop-symbolic', 'Disable boot restoration', lambda *_: self.run('disable'))],
        ):
            row = Gtk.Box(spacing=8)
            for icon, title, callback in actions:
                button = Gtk.Button(icon_name=icon, tooltip_text=title, hexpand=True)
                button.connect('clicked', callback)
                row.append(button)
                self.buttons.append(button)
            box.append(row)
        self.boot = Gtk.Label(wrap=True, xalign=0)
        box.append(self.boot)
        self.status = Gtk.Label(wrap=True, xalign=0, selectable=True)
        box.append(self.status)
        self.refresh_selector()
        self.refresh_boot()
        if self.load_error:
            self.status.set_text('Cannot load profiles: ' + self.load_error)
            for button in self.buttons:
                button.set_sensitive(False)

    def refresh_boot(self):
        try:
            profile = validate(json.loads(CONFIG.read_text()))
            self.boot.set_text('Boot profile (saved copy): ' + profile['name'])
        except FileNotFoundError:
            self.boot.set_text('Boot restoration: off')
        except (OSError, ValueError) as exc:
            self.boot.set_text('Cannot read boot profile: ' + str(exc))

    def refresh_selector(self, selected=None):
        self.names = sorted(self.profiles)
        self.selector.set_model(Gtk.StringList.new(self.names))
        if self.names:
            self.selector.set_selected(self.names.index(selected) if selected in self.names else 0)
            self.load_selected()
        else:
            self.new()

    def load_selected(self, *_):
        index = self.selector.get_selected()
        if index >= len(self.names):
            return
        profile = self.profiles[self.names[index]]
        self.name.set_text(profile['name'])
        for key, control in self.controls.items():
            value = profile['settings'].get(key)
            control.set_selected(list(OPTIONS[key][1]).index(value) + 1 if value is not None else 0)

    def new(self, *_):
        self.name.set_text('')
        for control in self.controls.values():
            control.set_selected(0)

    def draft(self):
        return validate({'name': self.name.get_text(), 'settings': {
            key: list(OPTIONS[key][1])[control.get_selected() - 1]
            for key, control in self.controls.items() if control.get_selected() > 0
        }})

    def persist(self, profiles, selected=None):
        atomic_json(self.path, list(profiles.values()))
        self.profiles = profiles
        self.refresh_selector(selected)

    def save(self, *_):
        try:
            profile = self.draft()
            self.persist(dict(self.profiles, **{profile['name']: profile}), profile['name'])
            self.status.set_text('Profile saved')
        except (ValueError, OSError) as exc:
            self.status.set_text(str(exc))

    def rename(self, *_):
        try:
            index = self.selector.get_selected()
            if index >= len(self.names):
                raise ValueError('Select a profile first')
            old = self.names[index]
            profile = self.draft()
            if profile['name'] != old and profile['name'] in self.profiles:
                raise ValueError('A profile with that name already exists')
            updated = dict(self.profiles)
            del updated[old]
            updated[profile['name']] = profile
            self.persist(updated, profile['name'])
            self.status.set_text('Profile renamed; boot copy unchanged')
        except (ValueError, OSError) as exc:
            self.status.set_text(str(exc))

    def delete(self, *_):
        index = self.selector.get_selected()
        if index < len(self.names):
            try:
                updated = dict(self.profiles)
                del updated[self.names[index]]
                self.persist(updated)
                self.status.set_text('Profile deleted; boot copy unchanged')
            except OSError as exc:
                self.status.set_text(str(exc))

    def run(self, action):
        try:
            profile = self.draft() if action != 'disable' else None
            if action == 'enable' and self.profiles.get(profile['name']) != profile:
                raise ValueError('Save this profile before selecting it for boot')
            if not Path(HELPER).exists():
                raise ValueError('Install the updated package to use profile actions')
        except ValueError as exc:
            self.status.set_text(str(exc))
            return
        self.set_sensitive(False)
        self.status.set_text('Waiting for authorization')

        def worker():
            try:
                result = subprocess.run(['pkexec', HELPER, action],
                                        input=json.dumps(profile) if profile else '',
                                        text=True, capture_output=True, timeout=120)
                message = (result.stdout + result.stderr).strip()
                if result.returncode:
                    message = message or 'Authorization cancelled or operation failed'
                else:
                    message = message or ('Boot profile saved' if action == 'enable' else 'Boot restoration disabled')
            except (OSError, subprocess.TimeoutExpired) as exc:
                message = str(exc)
            GLib.idle_add(done, message)

        def done(message):
            self.set_sensitive(True)
            self.status.set_text(message)
            self.refresh_boot()
            return False

        threading.Thread(target=worker, daemon=True).start()
