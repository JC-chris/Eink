# Firmware

## Label (`label/`)

Doelplatform: **Nordic nRF54L15**, **Zephyr / nRF Connect SDK**.

Aanwezig:

- `src/eink_image.h/.c` — decoder voor het beeldformaat uit de cloud (header, RLE, CRC32),
  streaming zodat het beeld direct naar het display-RAM gaat (een 7,3" Spectra 6-beeld is 192 kB,
  meer dan in SRAM past).
- `test/run.sh` — compileert de decoder op de PC en test hem tegen frames die de Python-backend
  maakt. Zo blijven firmware en cloud gegarandeerd compatibel.

Nog te bouwen (fase 1–2, zie [roadmap](../docs/08-roadmap.md)):

| Module | Basis |
|---|---|
| ESL-radio (PAwR sync, groepen, OTS-beeldoverdracht) | nRF Connect SDK `samples/bluetooth/esl/peripheral_esl` |
| Display-drivers per panel (SPI, LUT per temperatuur, BUSY-pin) | datasheets Good Display / E Ink; Zephyr `display`-API of eigen driver |
| Palet-index → panel-formaat (bv. 2 bitplanes voor BWR) | in de display-driver, gevoed door `eink_image_decode` |
| Telemetrie: batterij onder belasting, temperatuur, CRC getoond beeld | nRF54L15 SAADC + TEMP |
| NFC-koppeling (label-ID + productkoppeling met telefoon) | nRF54L15 NFCT |
| LED-commando's (zoeken / pick-to-light) | GPIO/PWM |
| OTA-firmware-update, gesigneerd | MCUboot + ESL/SMP |
| Productietest-modus | UART-commando's via testpads |

## Basisstation radio-coprocessor

Ook nRF54L15, basis `samples/bluetooth/esl/central_esl`, aangestuurd door de Linux-agent via UART.
De agent-kant is `basestation/eink_basestation/radio.py` (`NordicEslRadio`).
