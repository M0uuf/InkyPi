# Troubleshooting

## InkyPi Service not running

Check the status of the service:
```bash
sudo systemctl status inkypi.service
```

If the service is running, this should output `Active: active (running)`:
```bash
● inkypi.service - InkyPi App
     Loaded: loaded (/etc/systemd/system/inkypi.service; enabled; preset: enabled)
     Active: active (running) since Sun 2024-12-22 20:48:53 GMT; 28s ago
   Main PID: 48333 (bash)
      Tasks: 6 (limit: 166)
        CPU: 6.333s
     CGroup: /system.slice/inkypi.service
             ├─48333 bash /usr/local/bin/inkypi -d
             └─48336 python -u /home/pi/inky/src/inkypi.py -d
```

If the service is not running, check the logs for any errors or issues.

## Debugging

View the latest logs for the InkyPi service:
```bash
journalctl -u inkypi -n 100
```

Tail the logs:
```bash
journalctl -u inkypi -f
```

## Raspberry Pi Zero 2 W performance checklist

Raspberry Pi Zero 2 W can run InkyPi, but it is a low-resource system. Slow behavior usually comes from one of three places:

1. **Plugin generation**: Weather or Calendar fetching data, rendering HTML, starting Chromium, or drawing with Pillow.
2. **Image processing**: orientation, resize, enhancement, hashing, or display-buffer conversion.
3. **Physical E-Ink refresh**: the Waveshare panel itself. Full refreshes, especially on multi-color panels, can take many seconds regardless of CPU speed.

Do not expect Waveshare color E-Paper panels to update like an LCD. A 20-30 second full refresh can be normal on some panels and configurations.

### Recommended baseline settings

For Raspberry Pi Zero 2 W, start with conservative settings and optimize only after measuring:

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

Notes:

- `current_image_poll_interval_seconds`: avoid unnecessary Web UI polling. 15-30 seconds is a good range.
- `display_low_resource_mode`: enables cheaper final display-pipeline behavior.
- `display_resize_filter`: `bicubic` is a good speed/quality compromise on small Raspberry Pi systems.
- `performance_diagnostics`: enables detailed timing logs while diagnosing problems. Disable it again if you want quieter logs.
- `waveshare_clear_before_display`: disabling it can reduce update time, but may increase ghosting.
- `waveshare_sleep_after_display`: disabling it can avoid wake/reinitialize cost, but can increase power use.
- `waveshare_reinitialize_before_display`: keep it enabled unless sleep is also disabled and your panel has been tested.

### Recommended plugin settings

Use Fast renderer mode where possible:

- Weather: set renderer to **Fast** if you do not need the full HTML graph/styling.
- Calendar: set renderer to **Fast** if the simplified layout is enough.

Use HTML mode only when you need the richer layout. HTML mode can start Chromium and may be much slower on Zero 2 W.

This fork only supports Weather and Calendar as built-in plugins. Older advice about testing with removed plugins such as Clock, Screenshot, Image Upload, or third-party plugins does not apply to this fork.

### How to identify the bottleneck

Enable diagnostics in `src/config/device.json`:

```json
{
  "performance_diagnostics": true
}
```

Restart the service:

```bash
sudo systemctl restart inkypi.service
```

Watch the logs:

```bash
journalctl -u inkypi -f
```

Look for these timing groups:

- `Refresh diagnostics`: overall refresh phases such as playlist selection, plugin loading, plugin image generation, image hashing, display-manager processing, and config write.
- `HTML render diagnostics`: Jinja rendering and HTML screenshot work.
- `Chromium screenshot diagnostics`: Chromium startup/process and PNG load.
- `Display pipeline`: image save, orientation, resize, inversion, enhancement, display call, and total display pipeline time.
- `Waveshare`: panel init, clear, buffer conversion, display update, and sleep.

Interpretation:

- If `plugin image generation`, `HTML render diagnostics`, or `Chromium screenshot diagnostics` is slow, switch the plugin to Fast mode or simplify the plugin layout.
- If `Display pipeline resize` or `enhancement` is slow, use `display_low_resource_mode=true`, set `display_resize_filter` to `bicubic` or `bilinear`, and keep image enhancement settings at defaults.
- If `Waveshare display`, `Waveshare clear`, or `Waveshare sleep` is slow, the physical panel update is the bottleneck. Software can reduce overhead around it, but cannot make the panel instant.
- If the Web UI feels sluggish while refreshes are running, keep `web_server_threads` at least `2` and avoid opening many simultaneous refresh requests.

### Web UI polling

The main page checks the current display image periodically. On Zero 2 W, avoid very short intervals.

Recommended:

```json
{
  "current_image_poll_interval_seconds": 15
}
```

Use `30` seconds if the Web UI is still noticeably sluggish. The UI also triggers an immediate image update after manual refresh jobs complete, so aggressive background polling is usually unnecessary.

### Waveshare refresh expectations

Waveshare panels vary widely. Black/white panels are usually faster than multi-color panels. Larger and color panels often need long full refreshes.

The following settings can affect physical display time:

```json
{
  "waveshare_clear_before_display": true,
  "waveshare_sleep_after_display": true,
  "waveshare_reinitialize_before_display": true
}
```

Safe defaults prioritize correctness and panel stability. Only tune them after confirming that your panel still updates reliably and does not show unacceptable ghosting.

### Practical troubleshooting flow

1. Enable `performance_diagnostics`.
2. Trigger one manual refresh.
3. Check whether the slowest phase is plugin/HTML/Chromium, image processing, or Waveshare display.
4. If plugin/HTML/Chromium is slow, switch Weather/Calendar to Fast mode.
5. If image processing is slow, enable `display_low_resource_mode` and use `bicubic` or `bilinear` resize.
6. If Waveshare refresh is slow, accept the physical limit or cautiously test clear/sleep settings.
7. Increase `current_image_poll_interval_seconds` if the Web UI is still sluggish.
8. Disable `performance_diagnostics` again when you no longer need detailed logs.

## Restart the InkyPi Service

```bash
sudo systemctl restart inkypi.service
```


## Run InkyPi Manually

If the InkyPi service is not running, try manually running the startup script to diagnose. This should output the logs to the terminal and make it easier to troubleshoot any errors:

```bash
sudo /usr/local/bin/inkypi -d
```

## API Key not configured

The Weather plugin requires an API key when using OpenWeatherMap. API keys need to be configured in a .env file at the root of the project. See [API Keys](api_keys.md) for details.

## Weather Sunset/Sunrise Time is wrong

If the displayed time is incorrect, your timezone setting may not be configured. You can update this in the Settings page of the Web UI.

## Failed to retrieve weather data

```bash
Failed to retrieve weather data
ERROR - root - Failed to retrieve weather data: b'{"cod":401, "message": "Please note that using One Call 3.0 requires a separate subscription to the One Call by Call plan. Learn more here https://openweathermap.org/price. If you have a valid subscription to the One Call by Call plan, but still receive this error, then please see https://openweathermap.org/faq#error401 for more info."}'
```

InkyPi uses the One Call API 3.0 API which requires a subscription but is free for up to 1,000 requests a day. See [API Keys](api_keys.md) for instructions.

## Waveshare e-Paper EPD Devices

### Missing modules

Ensure that the necessary modules are available in the python environment. Waveshare requires:

- gpiozero
- lgpio
- RPi.GPIO

These are installed from `install/ws-requirements.txt` during installation.

### Screen not updating

Verify SPI configuration using `ls /dev/sp*`.  There should be two entries for _spidev0.0_ and _spidev0.1_.  

If only the first is visible, check _/boot/firmware/config.txt_. The regular install of InkyPi adds `dtoverlay=spi0-2cs` to this file.

### ERROR: Failed to download Waveshare driver

The installation script attempts to fetch the EPD driver library based on the -W argument provided. Please double-check that:
- You’ve entered the correct display model.
- The corresponding driver file exists in the [waveshare e-Paper github repository](https://github.com/waveshareteam/e-Paper/tree/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd).

Note: Some displays, such as the epd4in0e, are not included in the main library path above. Instead, they may be located under the [E-paper_Separate_Program](https://github.com/waveshareteam/e-Paper/tree/master/E-paper_Separate_Program) path. If your model is there, look under:
```bash
/RaspberryPi_JetsonNano/python/lib/waveshare_epd/
```

In this case, you’ll need to manually copy both the epdXinX.py and epdconfig.py files into:
```bash
InkyPi/src/display/waveshare_epd/
```

For example, to copy the driver and epdconfig files for epd13in3E (Waveshare Spectra 6 (E6) Full Color 13.3 inch display):
```bash
cd InkyPi/src/display/waveshare_epd/
curl -L -O https://raw.githubusercontent.com/waveshareteam/e-Paper/refs/heads/master/E-paper_Separate_Program/13.3inch_e-Paper_E/RaspberryPi/python/lib/epd13in3E.py
curl -L -O https://raw.githubusercontent.com/waveshareteam/e-Paper/refs/heads/master/E-paper_Separate_Program/13.3inch_e-Paper_E/RaspberryPi/python/lib/epdconfig.py
```

Additionally, you'll need the DEV_config* files in the same directory for your system. If you don’t know which file applies to your hardware, you can download all available DEV config files.
For example, for the epd13in3E display & Pi Zero 2 W, pull the following file:
```bash
curl -L -O https://raw.githubusercontent.com/waveshareteam/e-Paper/refs/heads/master/E-paper_Separate_Program/13.3inch_e-Paper_E/RaspberryPi/python/lib/DEV_Config_64_b.so
```

Once the files are in place, rerun the installation script. The script will detect the driver locally and skip the download step.

## Known Issues during Pi Zero W Installation

Due to limitations with the Pi Zero W, there are some known issues during the InkyPi installation process. For more details and community discussion, refer to this [GitHub Issue](https://github.com/fatihak/InkyPi/issues/5).

### Pip Installation Error

#### Error message
```bash
WARNING: Retrying (Retry(total=4, connect=None, read=None, redirect=None, status=None)) after connection broken by 'ProtocolError('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))':
```

#### Recommended solution
Manually install the required pip packages in the inkypi virtual environment:
```bash
source "/usr/local/inkypi/venv_inkypi/bin/activate"
pip install -r install/requirements.txt
deactivate
```
Restart the inkypi service to apply the changes:
```bash
sudo systemctl restart inkypi.service
```

## Colors look washed out or incorrect

Some color inaccuracies are expected due to the physical limitations of e-ink displays, especially on multi-color panels with a limited color palette and dithering.

InkyPi provides several image enhancement controls in the Settings page that can help improve how images appear on your display: Saturation, Contrast, Sharpness, Brightness. These adjustments are applied to images using the Pillow ImageEnhance module before they are displayed. You can experiment with these values to find what looks best for your specific panel and content.

For more details on how each setting behaves, see the [Pillow documentation](https://pillow.readthedocs.io/en/stable/reference/ImageEnhance.html).
