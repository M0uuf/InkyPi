# InkyPi

InkyPi is a focused Raspberry Pi + Waveshare E-Ink dashboard for weather and calendar information.

This repository is a fork of the original [fatihak/InkyPi](https://github.com/fatihak/InkyPi) project. The original project created the foundation for the web UI, plugin model, installation flow, and Raspberry Pi E-Ink dashboard experience. This fork builds on that work with appreciation and narrows the product direction toward a small, reliable, low-resource home dashboard.

## Project goal

The goal of this fork is not to be a general-purpose E-Ink plugin platform. It is intended to be a compact appliance-style dashboard:

- Raspberry Pi based
- Waveshare E-Ink displays only
- Weather and calendar as the only supported built-in plugins
- usable on low-resource devices such as Raspberry Pi Zero 2 W
- predictable refresh behavior
- reduced Chromium usage where possible
- simple web-based configuration from the local network

Keeping the scope small makes it easier to improve performance, reduce maintenance burden, and keep the device reliable for everyday use.

## Current scope

### Supported display hardware

This fork supports **Waveshare E-Ink displays only**.

Pimoroni/Inky display support and other non-Waveshare display paths have been removed from the supported product scope. A mock display path remains available for development and testing.

Waveshare displays use model-specific drivers from the Waveshare Python EPD library:

<https://github.com/waveshareteam/e-Paper/tree/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd>

When installing, pass the Waveshare model name without the `.py` extension, for example:

```bash
sudo bash install/install.sh -W epd7in3f
```

Displays based on the IT8951 controller are not supported. Very small panels are not recommended because the weather and calendar layouts need enough resolution to be readable.

### Supported plugins

Only these built-in plugins are supported:

- **Weather**: current conditions, metrics, and forecast views
- **Calendar**: calendar views from ICS-compatible sources such as Google, Outlook, Apple Calendar, and Nextcloud public/private ICS links

Previously bundled plugins and third-party plugin installation are intentionally out of scope for this fork.

### Renderer modes

Weather and Calendar both support two rendering modes:

- **HTML**: the default renderer. It keeps the richer layout and styling, but uses Chromium for HTML-to-image rendering.
- **Fast**: a simplified Pillow-based renderer. It avoids Chromium and is better suited to Raspberry Pi Zero class devices, but it does not aim to match every visual feature of the HTML renderer.

The renderer can be selected from the plugin settings page.

## Why this fork exists

The original InkyPi project is broad and extensible. This fork deliberately trades breadth for focus:

- fewer display backends
- fewer plugins
- fewer dependencies
- fewer expensive render paths
- clearer performance behavior on small Raspberry Pi devices

This makes the project easier to reason about and easier to optimize for a dedicated kitchen, hallway, office, or workshop E-Ink dashboard.

## Hardware

Recommended hardware:

- Raspberry Pi 4, Raspberry Pi 3, or Raspberry Pi Zero 2 W
- Raspberry Pi OS
- microSD card, 8 GB or larger
- Waveshare E-Ink display with a supported Python EPD driver
- suitable case, picture frame, or 3D-printed stand

For low-resource systems, especially Raspberry Pi Zero 2 W, prefer the Fast renderer modes and avoid unnecessary full refreshes.

## Installation

Start from a fresh Raspberry Pi OS installation where possible.

```bash
git clone https://github.com/M0uuf/InkyPi.git
cd InkyPi
sudo bash install/install.sh -W <waveshare-device-model>
```

Example for a Waveshare 7.3 inch color display:

```bash
sudo bash install/install.sh -W epd7in3f
```

The installer enables the required Raspberry Pi interfaces, installs dependencies, configures the service, and fetches the selected Waveshare driver.

After installation, reboot the Raspberry Pi when prompted.

More detailed installation notes are available in [docs/installation.md](./docs/installation.md).

## Updating

```bash
cd InkyPi
git pull
sudo bash install/update.sh [-W <waveshare-device-model>]
```

Use `-W` if the configured display type is missing, wrong, or needs to be changed.

## Uninstalling

```bash
sudo bash install/uninstall.sh
```

## Configuration highlights

The main device configuration is stored in:

```text
src/config/device.json
```

Important display/performance settings include:

- `display_type`: Waveshare model name, for example `epd7in3f`
- `web_server_threads`: number of Waitress worker threads
- `current_image_poll_interval_seconds`: main-page current-image polling interval
- `display_low_resource_mode`: force or disable low-resource display processing mode
- `display_resize_filter`: optional resize filter override, such as `bilinear`, `bicubic`, or `lanczos`
- `waveshare_clear_before_display`: whether to clear before each display update
- `waveshare_sleep_after_display`: whether to put the display to sleep after each update
- `waveshare_reinitialize_before_display`: whether to initialize the display before each update

The safe defaults preserve conservative E-Ink behavior. Disabling clear or sleep may reduce update time on some panels, but can increase ghosting, visual artifacts, or power use.

## Performance notes

Raspberry Pi Zero 2 W can run this project, but E-Ink refreshes and HTML rendering are inherently slow.

For best results on low-resource devices:

- use the Fast renderer for Weather and Calendar where acceptable
- keep the UI polling interval conservative
- avoid unnecessary manual refresh spam
- leave Waveshare safety defaults enabled until your panel has been tested
- use the timing logs to determine whether time is spent in plugin rendering, image processing, or physical display refresh

HTML-rendered plugin screenshots are cached to reduce repeated Chromium startup cost. The default cache directory is created with private permissions. If `INKYPI_HTML_RENDER_CACHE_DIR` is overridden, choose a private directory because screenshots can contain calendar or weather data.

## Development

Development without hardware is possible through the mock display configuration.

```bash
python -m pytest
python -m compileall src tests
```

The project intentionally keeps the supported runtime scope narrow. New work should preserve the Waveshare-only and Weather/Calendar-only product direction unless that scope is explicitly changed.

## Troubleshooting

See [docs/troubleshooting.md](./docs/troubleshooting.md) for common installation and runtime issues.

For issues specific to this fork, use the issue tracker in this repository:

<https://github.com/M0uuf/InkyPi/issues>

For the original upstream project, see:

<https://github.com/fatihak/InkyPi>

## Attribution and license

This fork is based on [fatihak/InkyPi](https://github.com/fatihak/InkyPi). Many thanks to the original author and contributors for creating and sharing the project.

Distributed under the GPL 3.0 License. See [LICENSE](./LICENSE) for details.

This project includes fonts and icons with separate licensing and attribution requirements. See [docs/attribution.md](./docs/attribution.md).

## Related projects

- [Original InkyPi](https://github.com/fatihak/InkyPi)
- [PaperPi](https://github.com/txoof/PaperPi)
- [InkyCal](https://github.com/aceinnolab/Inkycal)
- [PiInk](https://github.com/tlstommy/PiInk)
- [rpi_weather_display](https://github.com/sjnims/rpi_weather_display)
