# Vital Reflect

A smart mirror that only wakes up when somebody is standing in front of it.

Most smart mirrors keep the screen and camera on all day, even in an empty room. We wanted one that sits idle until it's needed, and that can also tell who it's talking to and hold a proper conversation. Four of us built it for the IMPECTUS National Hackathon 2025 at Sharad Institute of Technology, Yadrav, where it won first prize. We later wrote it up as a paper.

**Paper:** B. V. Pachapur, K. M. Munavalli, K. S. Kate, N. A. Belakud and S. Iyer, "Vital Reflect – The Personalized Interactive Mirror", *International Journal of Research Publication and Reviews*, vol. 6, no. 12, pp. 6303–6311, December 2025. The PDF is in [`docs/`](docs/Vital-Reflect-IJRPR-Dec-2025.pdf).

## How it works

An ultrasonic sensor on the frame notices when someone steps up to the mirror. Only then do the display, microphone and camera come on. The camera finds the face and checks it against the stored users, and a small CNN trained on a Kaggle facial-emotion dataset guesses the person's mood. Voice requests go to the Google Gemini API, so the mirror can answer ordinary questions instead of only a fixed list of commands. The screen runs [MagicMirror²](https://magicmirror.builders/) behind a two-way acrylic mirror, all driven by a Raspberry Pi 4B inside a wooden frame.

Numbers from our testing, as reported in the paper:

| What we measured | Result |
|---|---|
| Wake-up on approach | 96% |
| Face detection | 94% |
| User authorization | 91% |
| Emotion classification | 88% |
| Gemini response time | 1.2 to 1.8 seconds |

## What's in this repo

`vital_reflect.py` is the voice assistant and wake-up script that runs on the Pi. It:

- reads the ultrasonic sensor and starts MagicMirror when someone is within 40 cm
- listens offline with Vosk and wakes on the word "hello"
- answers a few built-in commands itself: meetings, routine, time and date
- sends anything else to Gemini and speaks a short answer back
- speaks with `pico2wave` if it's installed, and falls back to `pyttsx3`

The face authorization and emotion recognition code is not in this repo.

## Running it

You'll need a Raspberry Pi with an ultrasonic sensor (trigger on GPIO 23, echo on GPIO 24), a USB microphone and a speaker.

```bash
pip install -r requirements.txt
sudo apt install libttspico-utils   # optional, gives a clearer voice
```

Then:

1. Download a small Vosk English model and set `VOSK_MODEL_PATH` in the script.
2. Put your Gemini API key in `GEMINI_API_KEY`. Don't commit a real key.
3. Check the paths near the top of the file (`MEETING_JSON_PATH`, `MEETING_DISPLAY_PATH`, `MAGICMIRROR_PREFIX`). They're set for the user `pi123` on my Pi.
4. Run `python3 vital_reflect.py`.

The meetings command reads a JSON file shaped like this:

```json
{ "meetings": [ { "time": "10:00 AM", "title": "Project review" } ] }
```

## Team

Bhuvan V Pachapur, Kantesh M Munavalli, Kiran S Kate and Nitish A Belakud, guided by Dr. Sridhar Iyer, Dept. of Electronics and Communication Engineering, S. G. Balekundri Institute of Technology, Belagavi.
