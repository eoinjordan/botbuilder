# Camera and eyes (biped)

The default head is a Seeed Studio Round Display for XIAO with a XIAO ESP32S3
in its socket, screen forward as the robot's eyes, and a camera board on the
same head above it, lens forward and 10 degrees below level. `face` and
`camera.preset` in `config/assembly.json` say which head the assembly test
uses (`eyes_above`, `esp32cam`). The camera below the display, an ESP-EYE,
the camera alone in a fixed mount and the display stack turned round are
options with their own torso files; `stl/manifest.json` tags each.

Nothing here has been flashed, powered or fitted. No firmware is part of this
repository: no streaming firmware and no eyes.

## The display and what faces where

On the Round Display the XIAO plugs into the back and the screen is the
front. A XIAO ESP32S3 Sense has its camera on top of the XIAO, so in the
display's socket the camera looks out of the back, away from the screen.
Seeed's wiki says the pins are on the back and its camera project shows the
screen previewing what is behind it; it does not say it in a sentence.

So there are two ways to build the head, and the owner chose the first:

- **Screen forward as the eyes, a separate camera board looking forward**
  (`eyes_above`, `eyes_below`). This needs two microcontrollers: the XIAO for
  the display and the camera board's own ESP32 for the camera. The XIAO in
  the socket can be a plain XIAO ESP32S3; a Sense's camera would look
  backward there.
- **The stack turned round** (`stack_camera_forward`): the Sense camera
  looks forward and the screen faces a person behind the robot. One
  microcontroller, and it is the stack the owner already runs.

The Sense camera cannot be brought round to the front with the screen also
forward: its module is on a flex about 21 mm long overall, and the display is
about 40 mm across.

## What runs on the display today

The owner's repository executorch-zephyr-xiao-esp32s3 has Zephyr firmware for
exactly this stack (board `xiao_esp32s3/esp32s3/procpu/sense`, shield
`seeed_xiao_round_display`): it classifies camera frames with ExecuTorch and
draws the camera crop, the result and the timings on the screen. Its README
describes the panel as a GC9A01, 240 x 240, drawn in bands of 40 rows to save
RAM. Seeed's wiki gives 1.28 inch, 240 x 240 with capacitive touch.

## What eyes need from firmware

Not written. For the next step:

- A renderer for the round 240 x 240 panel: one large eye or two side by
  side, with a few states (open, blink, look left and right, sleepy). The
  band drawing in the existing firmware is the place to add it.
- An input that changes the state. With the camera on a second board that is
  a link between the two: a UART or I2C pair between the camera board and
  the XIAO, or Wi-Fi or BLE between them. The head has a wire path from the
  camera seat to the display for the first; nothing is wired.
- With `stack_camera_forward` the existing firmware already has the camera
  and the screen on one chip, but the screen then faces backward.

## Power for the display

The display runs and charges from its own 3.7 V lithium cell (JST 1.25
connector on the display, charged through the XIAO's USB-C port). The cell
is strapped under the deck front. The eyes therefore do not load the 5 V
supplies at all; see [power.md](power.md). The cell's size is not known:
the bay is drawn for 36 x 20 x 5.5 mm and 8.5 g.

## The camera boards

Three boards have a seat: the AI-Thinker ESP32-CAM (the default), the
Espressif ESP-EYE and, on the camera-only torsos, the Espressif
ESP32-S3-EYE.

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
