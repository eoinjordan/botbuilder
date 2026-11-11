# Camera

The torso carries a camera board in a mount at the front edge of the deck,
lens forward and 10 degrees below level. Three boards have a preset in the
design's generator and in `config/hardware.json`: the AI-Thinker ESP32-CAM
(the default), the Espressif ESP-EYE and the Espressif ESP32-S3-EYE. The
preset the assembly test uses is `camera.preset` in `config/assembly.json`.

Nothing here has been flashed, powered or fitted. No firmware is part of this
repository.

## The arrangement this reuses

The owner's unoq-braccio-sketchbot has a camera sketch,
`firmware/esp_eye_camera/esp_eye_camera.ino`, and a host side that reads it.
What that arrangement does, read from its source and README:

| Item | What the sketchbot does |
|---|---|
| Board the sketch is written for | Espressif ESP-EYE (ESP32, OV2640, 8 MB PSRAM); the pin map in the sketch is the ESP-EYE's (XCLK 4, SIOD 18, SIOC 23) |
| Build | Arduino IDE, Espressif esp32 boards package, board "ESP32 Wrover Module", partition "Huge APP (3MB No OTA)", no extra libraries |
| Wi-Fi credentials | `secrets.h` copied from `secrets.h.example`; an empty `WIFI_SSID` runs USB only |
| Transport over Wi-Fi | HTTP on port 80: `GET /capture` returns one JPEG, `GET /stream` returns MJPEG, `GET /` a status page; mDNS name `esp-eye.local` |
| Transport over USB | serial at 921600 baud; the host sends `C` and reads `0xA5 0x5A`, a 32-bit little-endian length and that many JPEG bytes |
| Frame | SVGA 800 x 600 JPEG (`FRAME_SIZE`, `JPEG_QUALITY`, `VFLIP`, `HMIRROR` at the top of the sketch) |
| Host side | `config/cameras.yaml`: `url: "http://esp-eye.local/capture"` for Wi-Fi or `serial: "auto"` for USB; read by `sketch_artist/cameras.py` |

It streams MJPEG over HTTP. It is not RTSP. An RTSP client will not open it;
a browser, `ffplay http://esp-eye.local/stream` or OpenCV will.

## Using it on this robot

Flash the same sketch with the same settings and read it the same way:

    stream     http://esp-eye.local/stream
    snapshot   http://esp-eye.local/capture

This repository has no host-side camera consumer, so there is no
configuration here to point at the stream. The walking controller does not
use the camera.

## Which board: an open point

The owner named the AI-Thinker ESP32-CAM as the board he used on the
sketchbot, and it is the default preset here. The sketchbot's sketch and its
`config/cameras.yaml` are written for the ESP-EYE. The two boards differ in
ways that matter for "the same firmware":

- The camera pins differ. The sketch's pin block has to be replaced by the
  AI-Thinker one (the `CAMERA_MODEL_AI_THINKER` block of the esp32 package's
  CameraWebServer example) before it will run on an ESP32-CAM. That change
  has not been made or tested here.
- The ESP32-CAM has no USB connector. The sketch's USB transport and the
  `serial:` host setting do not apply; only Wi-Fi does. It is flashed through
  a USB serial adapter on U0R, U0T and GND with IO0 held to GND at reset.
- The ESP32-CAM has 4 MB of PSRAM against the ESP-EYE's 8 MB. The sketch's
  double frame buffer at SVGA may need a smaller frame size.

If the board on the sketchbot was the ESP-EYE, set `CAMERA = 'esp_eye'` in
the design's `build.py` and `"preset": "esp_eye"` in `config/assembly.json`,
then regenerate. The ESP-EYE torso and fit piece are generated either way.

## Power

| Board | Supply | Current | Source |
|---|---|---|---|
| AI-Thinker ESP32-CAM | 5 V on the 5V and GND header pins | 180 mA with the flash LED off, 310 mA with it at maximum | AI-Thinker ESP32-CAM specification V1.0 (see `config/hardware.json`) |
| ESP-EYE | 5 V on Micro-USB | not published; allow 0.5 A | Espressif ESP-EYE getting-started guide (the USB port powers the whole board) |
| ESP32-S3-EYE | 5 V on Micro-USB | not published; allow 0.5 A | Espressif ESP32-S3-EYE getting-started guide |

Feed the camera from the UNO Q's 5 V supply side or its own 5 V source, not
from the servo rail: a servo stall pulls that rail down and resets an ESP32.
Add 0.3 A to the 5 V budget in [power.md](power.md) for the ESP32-CAM. Which
pin of the UNO Q stack the 5 V is taken from has not been chosen or checked.

## The mount

Numbers and pictures: the "Camera mount" section of
[assembly.md](assembly.md). How the board is held, what is assumed about
each board and how to print the fit piece first: the design directory's
README.
