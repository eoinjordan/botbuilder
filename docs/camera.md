# Camera and eyes (biped)

The default head is a Seeed Studio Round Display for XIAO with a XIAO ESP32S3
in its socket, screen forward as the robot's eyes, and a camera board on the
same head above it, lens forward and 10 degrees below level. `face` and
`camera.preset` in `config/assembly.json` say which head the assembly test
uses (`eyes_above`, `esp_eye`). The camera below the display, an ESP32-CAM,
the camera alone in a fixed mount and the display stack turned round are
options with their own torso files; `stl/manifest.json` tags each.

No firmware is part of this repository. The camera runs the sketch in the
owner's sketchbot repository; the eyes have none yet.

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

The default camera board is the Espressif ESP-EYE. It has a Micro-USB
connector for power and flashing, and the owner's sketchbot repository has a
working sketch for it. The AI-Thinker ESP32-CAM has a seat too and stays a
preset; there is no firmware for it. The Espressif ESP32-S3-EYE has a seat
on the camera-only torsos.

The ESP-EYE is mounted with its USB connector up and its camera end down, so
that nothing has to be kept clear under the board and the head stays low
(124 mm above the deck instead of 149 mm). The design directory's README has
the comparison of the arrangements. Mounted this way the picture is upside
down, which the sketch corrects with two settings (below).

## Flashing the ESP-EYE

The sketch is the sketchbot's, used as it is:
https://github.com/eoinjordan/unoq-braccio-sketchbot/tree/main/firmware/esp_eye_camera

1. Arduino IDE: install the Espressif esp32 boards package from the Boards
   Manager.
2. Open `esp_eye_camera.ino`. Board: "ESP32 Wrover Module" (or "ESP32 Dev
   Module" with PSRAM enabled). Partition scheme: "Huge APP (3MB No OTA)". No
   extra libraries.
3. Copy `secrets.h.example` to `secrets.h` and put the Wi-Fi name and
   password in it.
4. At the top of the sketch set `VFLIP` and `HMIRROR` to 1, because the board
   stands connector up on this robot. If the picture then comes out upside
   down, set both back to 0.
5. Plug the ESP-EYE into the computer by its Micro-USB connector, choose its
   serial port and Upload. No adapter and no jumper are needed.
6. Open the Serial Monitor at 921600 baud. It prints
   `INFO Wi-Fi up: http://<ip>/ (http://esp-eye.local/)`.

## The stream

    stream     http://esp-eye.local/stream     MJPEG over HTTP, port 80
    snapshot   http://esp-eye.local/capture    one JPEG
    status     http://esp-eye.local/

Frames are SVGA 800 x 600 JPEG (`FRAME_SIZE` and `JPEG_QUALITY` at the top
of the sketch). It is MJPEG over HTTP, not RTSP: a browser,
`ffplay http://esp-eye.local/stream` or OpenCV open it, an RTSP client does
not. Over USB the same sketch answers a `C` on its serial port (921600 baud)
with one length-framed JPEG; the sketchbot's `sketch_artist/cameras.py` reads
either. This repository has no host-side camera consumer, and the walking
controller does not use the camera.

## Power for the camera

| Board | Supply | Current | Source |
|---|---|---|---|
| ESP-EYE | 5 V on Micro-USB | not published; allow 0.5 A | Espressif ESP-EYE getting-started guide (the USB port powers the whole board) |
| AI-Thinker ESP32-CAM | 5 V on the 5V and GND header pins | 180 mA with the flash LED off, 310 mA with it at maximum | AI-Thinker ESP32-CAM specification V1.0 (see `config/hardware.json`) |
| ESP32-S3-EYE | 5 V on Micro-USB | not published; allow 0.5 A | Espressif ESP32-S3-EYE getting-started guide |

The ESP-EYE takes 5 V on its Micro-USB connector and nothing else is
documented. Two ways to feed it on the robot:

- A USB cable to a 5 V USB source: a small power bank, or the UNO Q's USB-C
  port as on the sketchbot, where the UNO Q is the USB host and can also read
  frames over the same cable. The UNO Q then has to be powered another way
  than through that port.
- The head's own battery cannot feed it directly: the display's cell is
  3.7 V and the ESP-EYE's connector wants 5 V. A 5 V boost converter between
  the cell and a Micro-USB plug would do it and keep the head self-contained;
  none is drawn or chosen.

Do not take it from the servo rail: a servo stall pulls that rail down and
resets an ESP32. Add 0.5 A to the 5 V budget in [power.md](power.md) if it
shares the controller's supply.

## The ESP32-CAM, if it is used instead

Set `CAMERA = 'esp32cam'` in the design's `build.py` and
`"preset": "esp32cam"` in `config/assembly.json`, then regenerate; its torso
and fit piece are generated either way. The sketchbot's sketch does not run
on it as it is: the camera pin block has to be replaced by the AI-Thinker
one, there is no USB connector (flash through a USB serial adapter on U0R,
U0T and GND with IO0 held to GND at reset), and it has 4 MB of PSRAM against
8 MB. None of that has been written here.

## The mount

Numbers and pictures: the "Camera mount" section of
[assembly.md](assembly.md). How the board is held, what is assumed about
each board and how to print the fit piece first: the design directory's
README.
