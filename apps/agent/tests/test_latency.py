import time
import logging
from latency import TurnTimer


def test_turn_timer_logs(caplog):
    caplog.set_level(logging.INFO, logger="divineruin.latency")

    timer = TurnTimer()
    timer.start()
    time.sleep(0.01)
    timer.mark("stt_done")
    time.sleep(0.01)
    timer.mark("tts_first_byte")
    timer.finish()

    assert any("LATENCY" in record.message for record in caplog.records)


def test_turn_timer_without_marks():
    timer = TurnTimer()
    timer.start()
    timer.finish()
