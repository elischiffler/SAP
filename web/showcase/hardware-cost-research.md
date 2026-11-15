# PAIGER hardware cost research

November 15, 2026. USD per complete two-device kit: one phone-side BLE/Wi-Fi bridge plus one user-side button/speaker device. Planning estimates, not supplier quotations. No purchases made.

## Verified price anchors

- Raspberry Pi Zero 2 W: official $15 reference; no verified volume discount. https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/
- Seeed XIAO ESP32-C3: approximately $4.90–4.99 per board. https://www.seeedstudio.com/Seeed-XIAO-ESP32C3-p-5431.html
- Seeed C3 tape/reel search listing showed $3.40 at 10+, but the live extracted page did not expose pricing. Treat this as provisional, confirm a quote. This variant explicitly excludes its external antenna. https://www.seeedstudio.com/Seeed-Studio-XIAO-ESP32C3-Tape-Reel-p-6471.html
- Adafruit MAX98357A DAC/amplifier board: $5.95 single, $4.76 at 100+. Listed out of stock when checked; reference pricing only. https://www.adafruit.com/product/3006
- Adafruit miniature speaker: $1.95 single, $1.56 at 100+. Listed out of stock. Match amplifier gain/output to the speaker's low power rating. https://www.adafruit.com/product/1890
- Espressif lists an ESP32-S3-WROOM-1-N8R2 module sample reference of $3.35. This is a module, not a complete powered development board or assembled product. https://www.espressif.com/products/modules

## Keep the Raspberry Pi: approximately 100 kits

Assumes Zero 2 W, not a larger Pi, USB-powered devices, existing USB power adapters supplied by the customer, simple enclosures, no battery. Cost allowances below are estimates except the listed board/audio anchors.

| Item | Per kit |
| --- | ---: |
| Phone bridge, including antenna allowance | $5 |
| Pi Zero 2 W | $15 |
| microSD | $3–5 |
| DAC/amplifier | $4.76 |
| Speaker | $1.56 |
| Button, LED, wiring/connectors | $1–2 |
| USB cables and two simple enclosures | $3–6 |
| Assembly and basic test | $2–5 |
| Total | $35.32–44.32 |

Round to $35–45. The processor boards, DAC/amplifier, and speaker alone total $26.32. The former $25 assumption is not a defensible complete Pi-kit cost based on these anchors. Buying 100 units does not by itself imply a much cheaper Pi.

## Custom microcontroller design: approximately 1,000 kits

Engineering target only; requires firmware port, PCB design, component sourcing and manufacturing quotes. Both devices remain in the kit. USB-powered, customer supplies power adapters.

| Item | Target per kit |
| --- | ---: |
| Phone-side BLE/Wi-Fi module | $2–3 |
| Speaker-side Wi-Fi module with flash/PSRAM | $3–4 |
| Audio DAC/amplifier and speaker | $2–3 |
| Two PCBs, power regulation, USB, button/LED, passives | $4–6 |
| Two simple enclosures and cables | $3–5 |
| Assembly, programming and test | $4–7 |
| Total | $18–28 |

The main saving is replacing Linux/Pi/microSD with a microcontroller. Server-side AI and speech stay on the server. Espressif supports network audio and I2S output: https://github.com/espressif/esp-adf and https://documentation.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/i2s.html

This is technically plausible, not validated for this firmware. Preserve TLS, authentication, button handling, download verification, and acknowledgment semantics. Current Pi code validates a complete WAV before playback, with files up to 5 MB; budget enough PSRAM/storage or revise and test this deliberately. Wi-Fi provisioning and reconnection also need implementation. Do not assume the existing Python/ALSA client runs unchanged on ESP32.

Battery portability adds a provisional $4–8 for the pager's cell, charging/protection and power circuitry, producing a $22–36 custom-kit target. Capacity, runtime and supplier choices remain unknown; this is not a battery quote. Phone bridge remains USB powered. Both endpoints need internet access over Wi-Fi; no cellular modem/service is included.

All totals exclude freight, duties/tax, packaging, fulfillment, returns, cloud/AI costs, development, tooling and compliance/testing. These are build targets, not landed COGS or profit estimates. At $59 retail and $18–28 build, $31–41 remains before these costs. Keep $59 as the price hypothesis until willingness to pay and operating costs are measured.
