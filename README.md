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
- `performance_diagnostics`: enable structured timing logs for refresh phases
- `waveshare_clear_before_display`: whether to clear before each display update
- `waveshare_sleep_after_display`: whether to put the display to sleep after each update
- `waveshare_reinitialize_before_display`: whether to initialize the display before each update

The safe defaults preserve conservative E-Ink behavior. Disabling clear or sleep may reduce update time on some panels, but can increase ghosting, visual artifacts, or power use.

## Web UI security

By default, the Web UI is intended for a trusted local network only. Do not expose it directly to the internet or an untrusted Wi-Fi network.

For optional protection, set an admin token in either the environment or device config:

```bash
export INKYPI_ADMIN_TOKEN="choose-a-long-random-token"
```

or:

```json
{
  "web_admin_token": "choose-a-long-random-token"
}
```

When an admin token is configured:

- browser users must log in at `/login`
- mutating requests require CSRF protection
- API-style clients can send `Authorization: Bearer <token>` or `X-InkyPi-Admin-Token: <token>`

If no admin token is configured, authentication and CSRF checks are disabled for first-run appliance setup. In that mode the Web UI must remain on a trusted LAN.

## Raspberry Pi Zero 2 W performance

Raspberry Pi Zero 2 W is supported, but it should be treated as a low-resource target. It can run the dashboard, but it will not behave like a Raspberry Pi 4.

There are three different costs that are easy to confuse:

1. **Plugin data and rendering time**: Weather or Calendar data fetching, HTML rendering, Chromium startup, or Pillow drawing.
2. **Image processing time**: orientation, resize, enhancement, hashing, and display-buffer conversion.
3. **Physical E-Ink refresh time**: the actual Waveshare panel update. Color panels and full refreshes can take many seconds, and software changes cannot make the physical panel instant.

Recommended Zero 2 W settings:

```json
{
  "current_image_poll_interval_seconds": 15,
  "display_low_resource_mode": true,
  "display_resize_filter": "bicubic",
  "performance_diagnostics": true,
  "waveshare_clear_before_display": true,
  "waveshare_sleep_after_display": true,
  "waveshare_reinitialize_before_display": true
}
```

Recommended plugin choices:

- use the **Fast** renderer for Weather and Calendar when the simplified layout is acceptable
- use the **HTML** renderer only when the richer layout is worth the extra Chromium cost
- keep refresh intervals realistic; weather and calendar dashboards usually do not need constant updates
- avoid repeated manual refresh clicks; manual refresh jobs are serialized and the E-Ink panel still needs time

Waveshare tuning options can reduce update time on some panels, but start with the safe defaults. Only disable `waveshare_clear_before_display` or `waveshare_sleep_after_display` after testing your specific display. Disabling clear can increase ghosting. Disabling sleep can increase power use. If the panel is put to sleep, InkyPi will reinitialize it before the next update.

Use diagnostics to find the real bottleneck:

```json
{
  "performance_diagnostics": true
}
```

Then check the service logs:

```bash
journalctl -u inkypi -f
```

Look for these timing groups:

- `Refresh diagnostics`: playlist selection, plugin image generation, hashing, display-manager processing, config write
- `HTML render diagnostics`: Jinja and HTML screenshot work
- `Chromium screenshot diagnostics`: Chromium process and PNG load
- `Display pipeline`: save, orientation, resize, enhancement, concrete display call
- `Waveshare`: init, clear, buffer conversion, display, sleep

If `plugin image generation` or `Chromium screenshot` dominates, switch that plugin to Fast mode. If `Waveshare display` dominates, the panel refresh itself is the limiting factor. See [docs/troubleshooting.md](./docs/troubleshooting.md#raspberry-pi-zero-2-w-performance-checklist) for a detailed checklist.

## Performance notes

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
