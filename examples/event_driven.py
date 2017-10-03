#!/usr/bin/env python3

import queue
import threading
import time

import mortise
from mortise import State


class Ping(State):
    def on_state(self, st):
        if st.msg:
            print("Ping: ", st.msg['data'])
            return Pong


class Pong(State):
    def on_state(self, st):
        if st.msg:
            print("Pong: ", st.msg['data'])
            return Ping


class ErrorState(State):
    def on_state(self, st):
        pass


def loop(msg_queue):
    # msg_queue should be accessible to another thread which is
    # handling IPC traffic or otherwise generating events to be
    # consumed by the state machine

    fsm = mortise.StateMachine(
        initial_state=Ping,
        final_state=mortise.DefaultStates.End,
        default_error_state=ErrorState,
        msg_queue=msg_queue,
        log_fn=print)

    # Initial kick of the state machine for setup
    fsm.tick()

    while True:
        fsm.tick(msg_queue.get())


def msg_loop(msg_queue):
    # NOTE: The messages consumed by Mortise are content agnostic, the
    # implementation / checking of message type is up to the user.

    idx = 0
    while True:
        messages = ['foo', 'bar', 'baz']
        idx += 1
        idx %= len(messages)
        msg_queue.put({'data': messages[idx]})
        time.sleep(1)


def main():
    msg_queue = queue.Queue()
    mortise_t = threading.Thread(target=loop, kwargs={'msg_queue': msg_queue})
    msg_t = threading.Thread(target=msg_loop, kwargs={'msg_queue': msg_queue})

    mortise_t.daemon = True
    msg_t.daemon = True

    mortise_t.start()
    msg_t.start()

    mortise_t.join()
    msg_t.join()

main()
