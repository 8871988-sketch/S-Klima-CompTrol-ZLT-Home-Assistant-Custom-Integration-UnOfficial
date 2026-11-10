# Changelog

## 0.2.0 – 2026-11-10

- Glitch filter: "no data" markers of the CompTrol ZLT (`-2147483648`) are detected and the last good values are kept
- Filter alarm is accepted after 10 polls in a row, fault and online after 3 – no more false notifications
- Up to 3 failed polls keep the last state instead of making all entities unavailable
- Debug log shows ignored glitches with the raw values

## 0.1.1 – 2026-11-09

- First version: config flow, climate entity per indoor unit, room temperature, error code, fault, filter, online, power/energy, outside temperature
- Re-authentication and polling interval option
- Translations: English, German, Ukrainian
