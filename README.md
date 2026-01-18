# LG Gram Manager

GTK4 application for managing LG Gram laptop features on Linux.

## Features

- Reader mode (blue light filter)
- FN lock toggle
- Fan mode (optimal, silent, performance)
- USB charging when powered off
- Battery care (80% charge limit)
- Keyboard backlight control
- Touchpad LED control

## Requirements

- LG Gram laptop with the `lg-laptop` kernel module
- Linux kernel 4.17+
- GTK4 and libadwaita
- Python 3.8+

## Installation

```bash
sudo dpkg -i lg-gram-manager_1.0.0_amd64.deb
```

Or run from source:

```bash
python3 lg_gram_manager_gtk.py
```

## Building

```bash
./build.sh
```

The .deb package will be output to `dist/`.

## Troubleshooting

If the driver is not loaded:

```bash
sudo modprobe lg-laptop
```

To load on boot:

```bash
echo "lg-laptop" | sudo tee -a /etc/modules
```
