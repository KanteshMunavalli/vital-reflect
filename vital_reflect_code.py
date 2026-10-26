#!/usr/bin/env python3
"""
Vital Reflect - Combined predefined commands + short Gemini responses (Alexa/Siri style)

Requirements:
- python3
- pip install vosk sounddevice pyttsx3 requests
- VOSK model at VOSK_MODEL_PATH (small model recommended)
- Optional: pico2wave installed (sudo apt install libttspico-utils) for crisper voice
- Set GEMINI_API_KEY with your Google Generative Language API key
"""

import RPi.GPIO as GPIO
import time
import threading
import requests
import pyttsx3
import queue
import json
import sounddevice as sd
import vosk
import subprocess
import os
import datetime
import shutil

# ---------------- CONFIG ----------------
TRIG_PIN = 23
ECHO_PIN = 24
VOSK_MODEL_PATH = "/home/pi123/vosk_models/vosk-model-small-en-us-0.15"  # update if needed
MIC_RATE = 16000
MAX_DISTANCE_CM = 40
MEETING_JSON_PATH = "/home/pi123/meeting_data.json"
MEETING_DISPLAY_PATH = "/home/pi123/MagicMirror/modules/MeetingDisplay/meetings.txt"
MAGICMIRROR_PREFIX = "/home/pi123/MagicMirror"
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"  # <-- replace with your key
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
GEMINI_TIMEOUT = 4  # seconds - keep short for snappy replies
MAX_GEMINI_TOKENS = 60  # encourage short answers
USE_PICO2WAVE_IF_AVAILABLE = True  # If pico2wave exists, use it for crisper voice
# ----------------------------------------

# ---------------- GPIO SETUP ----------------
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(TRIG_PIN, GPIO.OUT)
GPIO.setup(ECHO_PIN, GPIO.IN)

# ---------------- TTS SETUP ----------------
tts_lock = threading.Lock()

# Check for pico2wave binary for crisper TTS (optional)
PICO_BIN = shutil.which("pico2wave")

def tts_pico(text):
    """Use pico2wave (if available) to generate WAV, then play it with aplay."""
    try:
        safe_filename = "/tmp/vital_reflect_tts.wav"
        cmd = f"pico2wave -w={safe_filename} \"{text.replace('\"','')[:1500]}\" && aplay {safe_filename}"
        subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()
    except Exception as e:
        # fallback to pyttsx3
        tts_pyttsx3(text)

# pyttsx3 fallback
tts_engine = None
def init_pyttsx3():
    global tts_engine
    try:
        tts_engine = pyttsx3.init()
        voices = tts_engine.getProperty('voices')
        # Try to pick a female English voice
        picked = False
        for v in voices:
            name = (v.name or "").lower()
            vid = (v.id or "").lower()
            if ("female" in name or "female" in vid or "english" in name) and not picked:
                try:
                    tts_engine.setProperty('voice', v.id)
                    picked = True
                except Exception:
                    pass
        # set rate & volume for clarity
        tts_engine.setProperty('rate', 170)
        try:
            tts_engine.setProperty('volume', 1.0)
        except Exception:
            pass
    except Exception as e:
        tts_engine = None

def tts_pyttsx3(text):
    """Speak text with pyttsx3 (blocking inside thread)"""
    if tts_engine is None:
        init_pyttsx3()
    if tts_engine:
        def _speak():
            with tts_lock:
                try:
                    tts_engine.say(text)
                    tts_engine.runAndWait()
                except Exception:
                    pass
        threading.Thread(target=_speak, daemon=True).start()
    else:
        print("No TTS engine available to speak:", text)

def speak(text, force_pico=False):
    """Unified speak function - uses pico2wave if available for crisper voice, else pyttsx3"""
    if USE_PICO2WAVE_IF_AVAILABLE and PICO_BIN and not force_pico is False:
        # Use a background thread so main loop stays responsive
        def _pico():
            with tts_lock:
                tts_pico(text)
        threading.Thread(target=_pico, daemon=True).start()
    else:
        tts_pyttsx3(text)

# ---------------- VOSK SETUP ----------------
if not os.path.exists(VOSK_MODEL_PATH):
    print("VOSK model not found at", VOSK_MODEL_PATH)
    print("Please download a small model and set VOSK_MODEL_PATH accordingly.")
    # continue; listen will fail if model missing

model = None
try:
    model = vosk.Model(VOSK_MODEL_PATH)
except Exception as e:
    print("Error loading VOSK model:", e)
    model = None

audio_q = queue.Queue()

def audio_callback(indata, frames, time_, status):
    audio_q.put(bytes(indata))

def listen_stream():
    """Yield recognized text segments from the microphone (uses VOSK)."""
    if model is None:
        # fallback: yield nothing
        while True:
            time.sleep(1)
            yield ""
    rec = vosk.KaldiRecognizer(model, MIC_RATE)
    try:
        with sd.RawInputStream(samplerate=MIC_RATE, blocksize=8000, dtype='int16',
                               channels=1, callback=audio_callback):
            print("🎤 Listening for speech...")
            while True:
                data = audio_q.get()
                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    if result.get('text'):
                        yield result['text']
                else:
                    partial = json.loads(rec.PartialResult())
                    if partial.get('partial'):
                        # yield partial to reduce latency; handlers ignore empty/very short partials
                        yield partial['partial']
    except Exception as e:
        print("Audio input error:", e)
        # block briefly then keep trying
        while True:
            time.sleep(1)
            yield ""

# ---------------- MAGICMIRROR ----------------
def start_magicmirror():
    try:
        subprocess.Popen(
            ["bash", "-c", f"DISPLAY=:0 npm start --prefix {MAGICMIRROR_PREFIX}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print("Error starting MagicMirror:", e)

# ---------------- GEMINI API (short answers) ----------------
def call_gemini_short(prompt):
    """
    Call Gemini but instruct it to be concise (short assistant style).
    Keep timeout small to maintain snappiness.
    """
    if not GEMINI_API_KEY or "YOUR_GEMINI_API_KEY_HERE" in GEMINI_API_KEY:
        return "I don't have the AI key configured."

    system_instruction = (
        "You are a concise helpful assistant. Reply in 1-2 short sentences. "
        "If user asks for time/date, provide only the requested info. "
        "Keep answer under 40 words."
    )
    try:
        headers = {"Content-Type": "application/json", "X-goog-api-key": GEMINI_API_KEY}
        body = {
            "content": [
                {"type": "system", "text": system_instruction},
                {"type": "user", "text": prompt}
            ],
            "maxOutputTokens": MAX_GEMINI_TOKENS
        }
        # Some deployments expect slightly different shape - we use the minimal shape and allow for 400 responses
        r = requests.post(GEMINI_URL, headers=headers, json=body, timeout=GEMINI_TIMEOUT)
        r.raise_for_status()
        resp = r.json()
        # Attempt to extract text from common fields:
        # Newer API versions may place text in different nested fields; try common paths
        text = None
        if isinstance(resp, dict):
            # try nested candidates
            if "candidates" in resp and isinstance(resp["candidates"], list):
                c = resp["candidates"][0]
                if isinstance(c, dict) and "content" in c:
                    # candidate content may include 'text' or 'parts'
                    cont = c["content"]
                    if isinstance(cont, dict) and "parts" in cont and isinstance(cont["parts"], list):
                        text = cont["parts"][0].get("text")
            # fallback simple
            if not text and "output" in resp and isinstance(resp["output"], dict):
                out = resp["output"]
                if "content" in out and isinstance(out["content"], list):
                    # find the first text piece
                    for piece in out["content"]:
                        if isinstance(piece, dict) and "text" in piece:
                            text = piece["text"]
                            break
        if not text:
            # try to stringify whole json as fallback (short)
            text = resp.get("text") if isinstance(resp, dict) else str(resp)
        # final fallback
        if not text:
            return "Sorry, I couldn't get an answer from the AI."
        # sanitize
        text = text.strip()
        # Keep short: take first sentence if it's long
        if len(text) > 300:
            text = text.split(".")[0] + "."
        return text
    except Exception as e:
        print("Gemini error:", e)
        return "I couldn't reach the AI right now."

# ---------------- MEETINGS / REMINDERS ----------------
def get_meeting_reminders():
    """Return string with meetings or no meetings message and update MagicMirror display."""
    try:
        if not os.path.exists(MEETING_JSON_PATH):
            return "There are no meetings scheduled today."
        with open(MEETING_JSON_PATH, "r") as f:
            data = json.load(f)
        meetings = data.get("meetings", [])
        if not meetings:
            # ensure display file updated
            os.makedirs(os.path.dirname(MEETING_DISPLAY_PATH), exist_ok=True)
            with open(MEETING_DISPLAY_PATH, "w") as ff:
                ff.write("No meetings scheduled today.")
            return "There are no meetings scheduled today."
        # Build text
        lines = []
        for m in meetings:
            t = m.get("time", "unknown")
            title = m.get("title", "Untitled")
            lines.append(f"{t} - {title}")
        out_text = "You have " + str(len(lines)) + " meetings today. " + " ; ".join(lines)
        # Update MM file
        os.makedirs(os.path.dirname(MEETING_DISPLAY_PATH), exist_ok=True)
        with open(MEETING_DISPLAY_PATH, "w") as ff:
            ff.write(out_text)
        return out_text
    except Exception as e:
        print("Meeting fetch error:", e)
        return "There are no meetings scheduled today."

# ---------------- ULTRASONIC SENSOR ----------------
def measure_distance():
    try:
        GPIO.output(TRIG_PIN, False)
        time.sleep(0.05)
        GPIO.output(TRIG_PIN, True)
        time.sleep(0.00001)
        GPIO.output(TRIG_PIN, False)

        pulse_start = time.time()
        timeout = time.time() + 0.04  # short timeout
        while GPIO.input(ECHO_PIN) == 0 and time.time() < timeout:
            pulse_start = time.time()
        pulse_end = time.time()
        timeout2 = time.time() + 0.04
        while GPIO.input(ECHO_PIN) == 1 and time.time() < timeout2:
            pulse_end = time.time()
        pulse_duration = pulse_end - pulse_start
        distance = pulse_duration * 17150
        if distance <= 0 or distance > 400:
            return 999
        return distance
    except Exception as e:
        # sensor read failed
        return 999

# ---------------- PREDEFINED RESPONSES ----------------
PREDEFINED_RESPONSES = {
    "hello": "Hello! I am Vital Reflect, your AI personalised assistant.",
    "hi": "Hi there! How can I assist you?",
    "good morning": "Good morning! Have a bright and productive day.",
    "good afternoon": "Good afternoon! Hope you're doing well.",
    "good evening": "Good evening! How may I help you?",
    "meetings": None,  # handled separately by get_meeting_reminders
    "meeting": None,
    "routine": "Here is your routine for today. You have no major tasks scheduled.",
    "who are you": "I am Vital Reflect, your smart mirror assistant.",
    "stop": "Stopping assistant."
}

def match_command(cmd):
    """Return a predefined response or special flag (like 'meetings')"""
    cmd = cmd.lower()
    # direct exact triggers first
    for key in PREDEFINED_RESPONSES:
        if key in cmd:
            return key  # return the matched key
    return None

# ---------------- MAIN LOOP ----------------
def main():
    print("Vital Reflect – waiting for presence...")
    greeted = False
    assistant_active = False
    listener = listen_stream()

    try:
        while True:
            distance = measure_distance()
            # presence detected
            if distance < MAX_DISTANCE_CM:
                if not greeted:
                    print("Person detected! Launching MagicMirror if not running...")
                    start_magicmirror()
                    # prompt user
                    speak("Hello. Say 'hello' to activate Vital Reflect.")
                    greeted = True
                    time.sleep(0.8)

                # process speech input stream
                try:
                    command = next(listener)
                except Exception as e:
                    command = ""
                if not command:
                    # no voice captured, small sleep
                    time.sleep(0.15)
                    continue
                command = command.strip()
                if not command:
                    continue

                print("Heard:", command)

                # If wake word present and assistant not active
                if "hello" in command.lower() and not assistant_active:
                    assistant_active = True
                    speak(PREDEFINED_RESPONSES.get("hello"))
                    continue

                # If assistant is active handle commands
                if assistant_active:
                    # Stop command turns off assistant
                    if "stop" in command.lower():
                        speak("Goodbye! Assistant deactivated.")
                        assistant_active = False
                        continue

                    # Greetings that respond immediately
                    matched = match_command(command)
                    if matched:
                        # Meetings handled specially
                        if matched in ("meeting", "meetings"):
                            # immediate local response
                            meeting_text = get_meeting_reminders()
                            speak(meeting_text)
                        else:
                            # normal predefined answer
                            resp = PREDEFINED_RESPONSES.get(matched)
                            if resp:
                                speak(resp)
                        continue

                    # Time/date local responses (fast local answer)
                    if "time" in command.lower():
                        now = datetime.datetime.now()
                        timestr = now.strftime("%I:%M %p").lstrip("0")
                        speak(f"The time is {timestr}")
                        continue
                    if "date" in command.lower() or "day" in command.lower():
                        today = datetime.date.today()
                        speak(today.strftime("Today is %A, %B %d, %Y"))
                        continue

                    # If not a predefined command -> ask Gemini (short)
                    # Run Gemini in a thread so TTS can start when response arrives without blocking recognition loop
                    def ask_gemini_and_speak(qtext):
                        ans = call_gemini_short(qtext)
                        speak(ans)

                    threading.Thread(target=ask_gemini_and_speak, args=(command,), daemon=True).start()
                    continue

                # If assistant not active and no wake word - ignore or optionally listen for 'hello' in partials
                # small delay to avoid hogging CPU
                time.sleep(0.12)

            else:
                # no one present
                greeted = False
                assistant_active = False
                time.sleep(0.25)

    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    # initialize pyttsx3 in main thread to avoid issues on some platforms
    try:
        init_pyttsx3()
    except Exception:
        pass
    main()