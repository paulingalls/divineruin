"""Generate local speech and play it once through the exact built-in speaker."""

import argparse
import array
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import wave
from pathlib import Path

VOICE = "Samantha"
RATE = 180
GAIN = 0.6
SPEAKER = "MacBook Pro Speakers, BuiltInSpeakerDevice"


def speaker_index(listing):
    matches = re.findall(r"\[(\d+)\]\s+" + re.escape(SPEAKER) + r"\s*$", listing, re.MULTILINE)
    if len(matches) != 1:
        raise RuntimeError("exactly one BuiltInSpeakerDevice output is required")
    return matches[0]


def status_endpoint(control, run_id):
    url = urllib.parse.urlsplit(control["fixture_url"])
    if (
        control.get("run_id") != run_id
        or url.scheme != "http"
        or url.hostname != "127.0.0.1"
        or not url.port
        or url.username
        or url.password
        or url.path != "/fixture"
    ):
        raise RuntimeError("control is stale or is not the owned loopback fixture")
    return urllib.parse.urlunsplit(
        (
            url.scheme,
            url.netloc,
            "/status",
            urllib.parse.urlencode({"run_id": run_id}),
            "",
        )
    )


def inspect_waveform(path):
    with wave.open(str(path), "rb") as source:
        rate, channels, width = (
            source.getframerate(),
            source.getnchannels(),
            source.getsampwidth(),
        )
        samples = array.array("h", source.readframes(source.getnframes()))
    if (rate, channels, width) != (48000, 1, 2) or not samples or max(map(abs, samples)) < 500:
        raise RuntimeError("waveform must contain voiced 48kHz mono PCM16")
    duration = len(samples) / rate
    if not 1 <= duration <= 25:
        raise RuntimeError("waveform has invalid duration")
    return {
        "sample_rate": rate,
        "channels": channels,
        "pcm_bits": 16,
        "duration_seconds": duration,
        "peak_pcm": max(map(abs, samples)),
    }


def generate_speech(directory, run_id, turns=(1, 2)):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/agent/tests"))
    from acceptance.choir_acoustic_source import marker_pcm

    aiff = directory / "local-speech.aiff"
    pcm = directory / "local-speech.wav"
    waveform = directory / "microphone-two-bursts.wav"
    if not pcm.exists():
        voices = subprocess.run(["say", "-v", "?"], check=True, capture_output=True, text=True).stdout
        if not any(line.startswith(VOICE + " ") for line in voices.splitlines()):
            raise RuntimeError(f"required local speech voice {VOICE} unavailable")
        subprocess.run(
            [
                "say",
                "-v",
                VOICE,
                "-r",
                str(RATE),
                "-o",
                str(aiff),
                "Your command reaches me.",
            ],
            check=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(aiff),
                "-ar",
                "48000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(pcm),
            ],
            check=True,
        )
    inspect_waveform(pcm)
    with wave.open(str(pcm), "rb") as source:
        speech = source.readframes(source.getnframes())
    with wave.open(str(waveform), "wb") as output:
        output.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        output.writeframes(b"\0" * 48000 + speech + b"\0" * 48000)
        for turn in turns:
            output.writeframes(marker_pcm(run_id, turn) + speech + b"\0" * 48000 * 3)
    metadata = {
        **inspect_waveform(waveform),
        "voice": VOICE,
        "speech_rate": RATE,
        "gain": GAIN,
        "speaker": SPEAKER,
        "speech": "Your command reaches me.",
    }
    (directory / "stimulus-waveform-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return waveform


def wait_for_microphone(endpoint, run_id, fetch=None, timeout=20):
    def request():
        with urllib.request.urlopen(endpoint, timeout=1) as response:
            return json.load(response)

    fetch = fetch or request
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = fetch()
        if current.get("run_id") != run_id:
            raise RuntimeError("microphone status belongs to another run")
        frames = current.get("microphone_frames")
        if isinstance(frames, int) and not isinstance(frames, bool) and frames >= 5:
            return
        time.sleep(0.05)
    raise TimeoutError("actual native microphone frames never became ready")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--sequence", action="store_true")
    args = parser.parse_args()
    endpoint = status_endpoint(json.loads(args.control.read_text()), args.run_id)
    args.artifacts.mkdir(parents=True, exist_ok=True)
    waveform = generate_speech(args.artifacts, args.run_id)
    listed = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "0",
            "-list_devices",
            "1",
            "-f",
            "audiotoolbox",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    device = speaker_index(listed.stderr)
    wait_for_microphone(endpoint, args.run_id)
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-re",
        "-i",
        str(waveform),
        "-af",
        f"volume={GAIN}",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        "-f",
        "audiotoolbox",
        "-audio_device_index",
        device,
        "-",
    ]
    if args.sequence:

        def play_wave(path):
            command[command.index("-i") + 1] = str(path)
            player = subprocess.Popen(command)
            (args.artifacts / "stimulus-active.json").write_text(
                json.dumps({"run_id": args.run_id, "pid": player.pid}) + "\n"
            )
            if player.wait() != 0:
                raise RuntimeError("sequenced speaker playback failed")

        turn = 0
        deadline = time.monotonic() + 1200
        played = []
        unrelated_played = False
        while time.monotonic() < deadline:
            with urllib.request.urlopen(endpoint, timeout=1) as response:
                status = json.load(response)
            if status.get("run_id") != args.run_id:
                raise RuntimeError("stale sequenced stimulus status")
            if status.get("choir_complete"):
                break
            if status.get("stimulus_fault") in (
                "withhold-microphone",
                "dm-tone-only",
                "unrelated-burst",
            ):
                if status["stimulus_fault"] == "unrelated-burst" and not unrelated_played:
                    waveform = generate_speech(args.artifacts, args.run_id, ())
                    play_wave(waveform)
                    unrelated_played = True
                time.sleep(0.05)
                continue
            requested = status.get("requested_turn", 0)
            if requested > turn:
                if requested != turn + 1 or status.get("command_receipts") != turn:
                    raise RuntimeError("out-of-order acoustic command request")
                waveform = generate_speech(args.artifacts, args.run_id, (requested,))
                play_wave(waveform)
                print(f"Played owned acoustic turn {requested}", flush=True)
                turn = requested
                played.append(turn)
            time.sleep(0.05)
        else:
            raise TimeoutError("sequenced acoustic encounter never completed")
    else:
        subprocess.run(command, check=True)
        played = [1, 2]
    (args.artifacts / "stimulus-playback.json").write_text(
        json.dumps({"run_id": args.run_id, "device": SPEAKER, "played_turns": played}) + "\n"
    )


if __name__ == "__main__":
    main()
