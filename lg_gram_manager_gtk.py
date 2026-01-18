#!/usr/bin/env python3
"""
LG Gram Manager (GTK4) - GUI for managing LG Gram laptop features on Linux
Controls reader mode, FN lock, battery care, fan mode, USB charge, and LEDs.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio
import os
import subprocess
from pathlib import Path
from typing import Optional, Callable
import threading


class SysfsInterface:
    """Interface for reading/writing sysfs files with proper permissions."""
    
    # Sysfs paths
    READER_MODE = "/sys/devices/platform/lg-laptop/reader_mode"
    FN_LOCK = "/sys/devices/platform/lg-laptop/fn_lock"
    BATTERY_THRESHOLD = "/sys/class/power_supply/CMB0/charge_control_end_threshold"
    FAN_MODE = "/sys/devices/platform/lg-laptop/fan_mode"
    USB_CHARGE = "/sys/devices/platform/lg-laptop/usb_charge"
    KBD_LED = "/sys/class/leds/kbd_backlight/brightness"
    TPAD_LED = "/sys/class/leds/tpad_led/brightness"
    
    # Alternative LED paths (some systems use different naming)
    KBD_LED_ALT = "/sys/class/leds/lg_laptop::kbd_backlight/brightness"
    TPAD_LED_ALT = "/sys/class/leds/lg_laptop::tpad/brightness"
    
    @classmethod
    def _get_led_path(cls, primary: str, alt: str) -> str:
        """Get the actual LED path that exists on the system."""
        if os.path.exists(primary):
            return primary
        elif os.path.exists(alt):
            return alt
        return primary
    
    @classmethod
    def get_kbd_led_path(cls) -> str:
        return cls._get_led_path(cls.KBD_LED, cls.KBD_LED_ALT)
    
    @classmethod
    def get_tpad_led_path(cls) -> str:
        return cls._get_led_path(cls.TPAD_LED, cls.TPAD_LED_ALT)
    
    @staticmethod
    def read_value(path: str) -> Optional[str]:
        """Read a value from sysfs."""
        try:
            with open(path, 'r') as f:
                return f.read().strip()
        except (IOError, PermissionError, FileNotFoundError) as e:
            print(f"Error reading {path}: {e}")
            return None
    
    @classmethod
    def write_value(cls, path: str, value: str, callback: Optional[Callable[[bool], None]] = None) -> bool:
        """Write a value to sysfs using sudo for root privileges."""
        try:
            with open(path, 'w') as f:
                f.write(str(value))
            if callback:
                GLib.idle_add(callback, True)
            return True
        except PermissionError:
            def run_pkexec():
                try:
                    # Use pkexec for polkit authentication - shows GUI prompt if needed
                    result = subprocess.run(
                        ['pkexec', 'tee', path],
                        input=str(value).encode(),
                        capture_output=True,
                        timeout=60
                    )
                    success = result.returncode == 0
                    if callback:
                        GLib.idle_add(callback, success)
                    return success
                except subprocess.TimeoutExpired:
                    print(f"Timeout writing to {path}")
                    if callback:
                        GLib.idle_add(callback, False)
                    return False
                except Exception as e:
                    print(f"Error using pkexec: {e}")
                    if callback:
                        GLib.idle_add(callback, False)
                    return False
            
            if callback:
                thread = threading.Thread(target=run_pkexec, daemon=True)
                thread.start()
                return True
            else:
                return run_pkexec()
        except (IOError, FileNotFoundError) as e:
            print(f"Error writing to {path}: {e}")
            if callback:
                GLib.idle_add(callback, False)
            return False
    
    @staticmethod
    def path_exists(path: str) -> bool:
        """Check if a sysfs path exists."""
        return os.path.exists(path)


class ToggleRow(Adw.ActionRow):
    """Toggle switch row for on/off features."""
    
    def __init__(self, title: str, subtitle: str, sysfs_path: str,
                 on_value: str = "1", off_value: str = "0"):
        super().__init__()
        
        self.sysfs_path = sysfs_path
        self.on_value = on_value
        self.off_value = off_value
        
        self.set_title(title)
        self.set_subtitle(subtitle)
        
        # Toggle switch
        self.switch = Gtk.Switch()
        self.switch.set_valign(Gtk.Align.CENTER)
        self.switch.connect("state-set", self._on_toggle)
        self.add_suffix(self.switch)
        self.set_activatable_widget(self.switch)
        
        self._updating = False
        self.refresh()
    
    def _on_toggle(self, switch, state):
        """Handle toggle state change."""
        if self._updating:
            return False
        
        value = self.on_value if state else self.off_value
        self.switch.set_sensitive(False)
        
        def on_complete(success):
            self.switch.set_sensitive(True)
            if not success:
                self._updating = True
                self.switch.set_active(not state)
                self._updating = False
        
        SysfsInterface.write_value(self.sysfs_path, value, callback=on_complete)
        return False
    
    def refresh(self):
        """Refresh the current value from sysfs."""
        if not SysfsInterface.path_exists(self.sysfs_path):
            self.switch.set_sensitive(False)
            return
        
        value = SysfsInterface.read_value(self.sysfs_path)
        if value is not None:
            self._updating = True
            self.switch.set_active(value == self.on_value)
            self._updating = False


class FanModeRow(Adw.PreferencesRow):
    """Fan mode control with 3 selectable buttons."""
    
    FAN_MODES = [
        {"value": 1, "icon": "weather-clear-symbolic", "label": "Silent"},
        {"value": 0, "icon": "emblem-default-symbolic", "label": "Optimal"},
        {"value": 2, "icon": "utilities-system-monitor-symbolic", "label": "Performance"},
    ]
    
    def __init__(self, sysfs_path: str):
        super().__init__()
        
        self.sysfs_path = sysfs_path
        self.current_mode = -1
        self.buttons = []
        
        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_box.set_margin_top(12)
        main_box.set_margin_bottom(12)
        main_box.set_margin_start(12)
        main_box.set_margin_end(12)
        
        # Title
        title = Gtk.Label(label="Fan Mode")
        title.add_css_class("title-4")
        title.set_halign(Gtk.Align.START)
        main_box.append(title)
        
        # Buttons box
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, homogeneous=True)
        
        for mode in self.FAN_MODES:
            btn = self._create_mode_button(mode)
            btn_box.append(btn)
        
        main_box.append(btn_box)
        self.set_child(main_box)
        
        self.refresh()
    
    def _create_mode_button(self, mode: dict) -> Gtk.Button:
        """Create a selectable mode button."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        
        # Icon
        icon = Gtk.Image.new_from_icon_name(mode['icon'])
        icon.set_pixel_size(32)
        box.append(icon)
        
        # Label
        label = Gtk.Label(label=mode['label'])
        box.append(label)
        
        btn = Gtk.Button()
        btn.set_child(box)
        btn.connect("clicked", lambda b, v=mode['value']: self._on_select(v))
        
        self.buttons.append((mode['value'], btn))
        return btn
    
    def _update_button_styles(self):
        """Update button appearance based on current selection."""
        for value, btn in self.buttons:
            if value == self.current_mode:
                btn.add_css_class("suggested-action")
                btn.remove_css_class("flat")
            else:
                btn.remove_css_class("suggested-action")
                btn.add_css_class("flat")
    
    def _on_select(self, value: int):
        """Handle mode button click."""
        if value == self.current_mode:
            return
        
        for _, btn in self.buttons:
            btn.set_sensitive(False)
        
        def on_complete(success):
            for _, btn in self.buttons:
                btn.set_sensitive(True)
            if success:
                self.current_mode = value
                self._update_button_styles()
        
        SysfsInterface.write_value(self.sysfs_path, str(value), callback=on_complete)
    
    def refresh(self):
        """Refresh current fan mode from sysfs."""
        if not SysfsInterface.path_exists(self.sysfs_path):
            for _, btn in self.buttons:
                btn.set_sensitive(False)
            return
        
        value = SysfsInterface.read_value(self.sysfs_path)
        if value is not None:
            try:
                self.current_mode = int(value)
                self._update_button_styles()
            except ValueError:
                pass


class BatteryRow(Adw.ActionRow):
    """Battery charge limit control."""
    
    def __init__(self, sysfs_path: str):
        super().__init__()
        
        self.sysfs_path = sysfs_path
        
        self.set_title("Battery Limit")
        self.set_subtitle("Limit charge to extend battery lifespan")
        
        # Dropdown
        self.dropdown = Gtk.DropDown.new_from_strings(["80%", "100%"])
        self.dropdown.set_valign(Gtk.Align.CENTER)
        self.add_suffix(self.dropdown)
        
        # Apply button
        self.apply_btn = Gtk.Button(label="Apply")
        self.apply_btn.set_valign(Gtk.Align.CENTER)
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", self._on_apply)
        self.add_suffix(self.apply_btn)
        
        self.refresh()
    
    def _on_apply(self, button):
        """Apply battery limit."""
        value = "80" if self.dropdown.get_selected() == 0 else "100"
        self.dropdown.set_sensitive(False)
        self.apply_btn.set_sensitive(False)
        
        def on_complete(success):
            self.dropdown.set_sensitive(True)
            self.apply_btn.set_sensitive(True)
            if not success:
                self.refresh()
        
        SysfsInterface.write_value(self.sysfs_path, value, callback=on_complete)
    
    def refresh(self):
        """Refresh battery charge limit."""
        if not SysfsInterface.path_exists(self.sysfs_path):
            self.dropdown.set_sensitive(False)
            self.apply_btn.set_sensitive(False)
            return
        
        value = SysfsInterface.read_value(self.sysfs_path)
        if value:
            self.dropdown.set_selected(0 if value == "80" else 1)


class KeyboardLightRow(Adw.ActionRow):
    """Keyboard backlight control."""
    
    def __init__(self, sysfs_path: str):
        super().__init__()
        
        self.sysfs_path = sysfs_path
        
        self.set_title("Keyboard Light")
        self.set_subtitle("Keyboard backlight brightness")
        
        # Toggle group
        self.toggle_group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.toggle_group.add_css_class("linked")
        self.toggle_group.set_valign(Gtk.Align.CENTER)
        
        self.buttons = []
        for label, value in [("Off", 0), ("Low", 127), ("High", 255)]:
            btn = Gtk.ToggleButton(label=label)
            btn.connect("toggled", self._on_toggle, value)
            self.toggle_group.append(btn)
            self.buttons.append((value, btn))
        
        self.add_suffix(self.toggle_group)
        
        self._updating = False
        self.refresh()
    
    def _on_toggle(self, button, value):
        """Handle toggle button click."""
        if self._updating or not button.get_active():
            return
        
        self._updating = True
        for v, btn in self.buttons:
            if v != value:
                btn.set_active(False)
        self._updating = False
        
        def on_complete(success):
            if not success:
                self.refresh()
        
        SysfsInterface.write_value(self.sysfs_path, str(value), callback=on_complete)
    
    def refresh(self):
        """Refresh keyboard LED brightness."""
        if not SysfsInterface.path_exists(self.sysfs_path):
            for _, btn in self.buttons:
                btn.set_sensitive(False)
            return
        
        value = SysfsInterface.read_value(self.sysfs_path)
        if value:
            try:
                val = int(value)
                self._updating = True
                for v, btn in self.buttons:
                    if val == 0:
                        btn.set_active(v == 0)
                    elif val <= 127:
                        btn.set_active(v == 127)
                    else:
                        btn.set_active(v == 255)
                self._updating = False
            except ValueError:
                pass


class LGGramManagerWindow(Adw.ApplicationWindow):
    """Main application window."""
    
    def __init__(self, app):
        super().__init__(application=app)
        
        self.set_title("LG Gram Manager")
        self.set_default_size(500, 750)
        
        self._create_widgets()
        self._check_driver()
    
    def _create_widgets(self):
        """Create all GUI widgets."""
        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        
        # Header bar
        header = Adw.HeaderBar()
        
        # Hamburger menu
        menu = Gio.Menu()
        menu.append("Refresh", "app.refresh")
        menu.append("Toggle Dark Mode", "app.toggle-theme")
        
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_menu_model(menu)
        header.pack_start(menu_btn)
        
        main_box.append(header)
        
        # Scrolled content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        
        # Content with clamp for max width
        clamp = Adw.Clamp()
        clamp.set_maximum_size(600)
        clamp.set_margin_top(12)
        clamp.set_margin_bottom(12)
        clamp.set_margin_start(12)
        clamp.set_margin_end(12)
        
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        
        # === Features Section ===
        features_group = Adw.PreferencesGroup()
        features_group.set_title("Features")
        
        self.reader_mode = ToggleRow(
            "Reader Mode",
            "Reduces blue light for eye comfort",
            SysfsInterface.READER_MODE
        )
        features_group.add(self.reader_mode)
        
        self.fn_lock = ToggleRow(
            "FN Lock",
            "Lock function keys as F1-F12",
            SysfsInterface.FN_LOCK
        )
        features_group.add(self.fn_lock)
        
        self.usb_charge = ToggleRow(
            "USB Charge (Off)",
            "Enable USB charging when laptop is off",
            SysfsInterface.USB_CHARGE
        )
        features_group.add(self.usb_charge)
        
        content.append(features_group)
        
        # === Battery Section ===
        battery_group = Adw.PreferencesGroup()
        battery_group.set_title("Battery")
        
        self.battery_limit = BatteryRow(SysfsInterface.BATTERY_THRESHOLD)
        battery_group.add(self.battery_limit)
        
        content.append(battery_group)
        
        # === LEDs Section ===
        leds_group = Adw.PreferencesGroup()
        leds_group.set_title("LEDs")
        
        self.kbd_led = KeyboardLightRow(SysfsInterface.get_kbd_led_path())
        leds_group.add(self.kbd_led)
        
        self.tpad_led = ToggleRow(
            "Touchpad LED",
            "Touchpad indicator LED",
            SysfsInterface.get_tpad_led_path()
        )
        leds_group.add(self.tpad_led)
        
        content.append(leds_group)
        
        # === Fan Mode Section ===
        fan_group = Adw.PreferencesGroup()
        fan_group.set_title("Cooling")
        
        self.fan_mode = FanModeRow(SysfsInterface.FAN_MODE)
        fan_group.add(self.fan_mode)
        
        content.append(fan_group)
        
        clamp.set_child(content)
        scrolled.set_child(clamp)
        main_box.append(scrolled)
        
        self.set_content(main_box)
    
    def _check_driver(self):
        """Check if the lg-laptop driver is loaded."""
        if not os.path.exists("/sys/devices/platform/lg-laptop"):
            dialog = Adw.AlertDialog()
            dialog.set_heading("Driver Not Found")
            dialog.set_body(
                "The lg-laptop driver doesn't appear to be loaded.\n\n"
                "Make sure you have the lg-laptop kernel module installed "
                "and loaded.\n\n"
                "Try: sudo modprobe lg-laptop"
            )
            dialog.add_response("ok", "OK")
            dialog.choose(self, None, None)
    
    def _refresh_all(self):
        """Refresh all controls."""
        self.reader_mode.refresh()
        self.fn_lock.refresh()
        self.usb_charge.refresh()
        self.battery_limit.refresh()
        self.kbd_led.refresh()
        self.tpad_led.refresh()
        self.fan_mode.refresh()
    
    def _toggle_theme(self, action, param):
        """Toggle between light and dark themes."""
        style_manager = Adw.StyleManager.get_default()
        if style_manager.get_dark():
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)


class LGGramManagerApp(Adw.Application):
    """Main application class."""
    
    def __init__(self):
        super().__init__(
            application_id="org.lg-gram-manager.gtk",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )
        self.win = None
    
    def do_activate(self):
        """Called when the application is activated."""
        self.win = LGGramManagerWindow(self)
        
        # Register actions
        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", lambda a, p: self.win._refresh_all())
        self.add_action(refresh_action)
        
        theme_action = Gio.SimpleAction.new("toggle-theme", None)
        theme_action.connect("activate", self.win._toggle_theme)
        self.add_action(theme_action)
        
        self.win.present()
    
    def do_shutdown(self):
        """Called when the application is shutting down."""
        Adw.Application.do_shutdown(self)


def main():
    """Main entry point."""
    app = LGGramManagerApp()
    return app.run(None)


if __name__ == "__main__":
    main()
