#!/bin/bash
#
# Install LG Gram Manager on Arch-based distros (CachyOS, EndeavourOS, ...)
# Mirrors what debian/rules + debian/postinst do on Debian.
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo ./install-arch.sh"
    exit 1
fi

TARGET_USER="${SUDO_USER:-}"

echo "Checking runtime dependencies..."
MISSING=""
for pkg in gtk4 libadwaita python-gobject polkit; do
    pacman -Q "$pkg" >/dev/null 2>&1 || MISSING="$MISSING $pkg"
done
if [ -n "$MISSING" ]; then
    echo "Installing:$MISSING"
    pacman -S --needed --noconfirm $MISSING
fi

echo "Installing files..."
install -D -m 755 lg_gram_manager_gtk.py /usr/bin/lg-gram-manager
install -D -m 644 debian/org.lg-gram-manager.gtk.desktop /usr/share/applications/org.lg-gram-manager.gtk.desktop
install -D -m 644 debian/org.lg-gram-manager.gtk.svg /usr/share/icons/hicolor/scalable/apps/org.lg-gram-manager.gtk.svg
install -D -m 644 debian/org.lg-gram-manager.policy /usr/share/polkit-1/actions/org.lg-gram-manager.policy
install -D -m 644 debian/99-lg-gram-manager.rules /usr/lib/udev/rules.d/99-lg-gram-manager.rules
rm -f /etc/udev/rules.d/99-lg-gram-manager.rules  # location used by older versions of this script

if ! getent group lg-gram >/dev/null 2>&1; then
    groupadd --system lg-gram
    echo "Created 'lg-gram' group"
fi

if [ -n "$TARGET_USER" ]; then
    usermod -aG lg-gram "$TARGET_USER"
    echo "Added user '$TARGET_USER' to 'lg-gram' group"
fi

echo "Reloading udev rules..."
udevadm control --reload-rules
udevadm trigger --subsystem-match=platform --subsystem-match=leds --subsystem-match=power_supply

command -v gtk-update-icon-cache >/dev/null 2>&1 && \
    gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || true
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database /usr/share/applications 2>/dev/null || true

echo
echo "Done. Launch with 'lg-gram-manager' or from your app menu."
echo "Log out and back in for the 'lg-gram' group to take effect"
echo "(until then, writes fall back to a polkit password prompt)."
