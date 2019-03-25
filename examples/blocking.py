#!/usr/bin/env python3

""" Example for blocking state machine that waits for the correct messages
    before moving onto the next state. Also shows an example of using local
    state values that are reset when the state is re-initialized. """

import queue
import random
import threading
import time

import mortise
from mortise import State


class Foo(State):
    """ Foo state keeps count of all "foo" messages it sees and prints out
        the current count. When it sees a "bar" message transitions to Bar
        state. All other messages are ignored and trapped."""
    TIMEOUT = 10

    def on_enter(self, st):
        # Re-initializes Foo count
        self.count = 0

    def on_state(self, st):
        if st.msg:
            print("Foo: ", st.msg['data'])
            if st.msg['data'] == 'bar':
                # Transition to Bar
                return Bar
            elif st.msg['data'] == 'foo':
                self.count += 1
                print("Foos: {}".format(self.count))
                # "Swallow" current message (don't trap it)
                return True

            # Otherwise return nothing which will trap messages

    def on_leave(self, st):
        print("Leaving Foo")
        if st.msg and st.msg['data'] == 'foo':
            # Will never be raised because returning True won't trigger
            # the on_leave handler
            raise Exception("Called on_leave when shouldn't have")


class Bar(State):
    """ Bar state keeps count of all "bar" messages it sees and prints out
        the current count. When it sees a "foo" message transitions to Foo
        state. All other messages are ignored and trapped."""
    TIMEOUT = 10

    def on_state(self, st):
        if st.msg:
            print("Pong: ", st.msg['data'])
            if st.msg['data'] == 'foo':
                # Transition to Foo
                return Foo
            elif st.msg['data'] == 'bar':
                # Count kept in shared state that will persist between state
                # transitions unlike Foo
                st.common.bars += 1
                print("Bars: {}".format(st.common.bars))
                # Remain in Bar state (don't trap message)
                return True

            # Otherwise remain in Bar and trap ignored message

    def on_leave(self, st):
        print("Leaving Bar")
        if st.msg and st.msg['data'] == 'bar':
            # Will never be raised because returning True won't trigger
            # the on_leave handler
            raise Exception("Called on_leave when shouldn't have")


class ErrorState(State):
    def on_state(self, st):
        pass


def trap_msg(st):
    """ Function the state machine calls when messsages are ignored in
        states (they return None)"""
    print("Trapped: {}".format(st.msg['data']))
    if st.msg['data'] != 'baz':
        # Will never be raised because returning True won't trap
        # messages and returning a new state won't trap.
        raise Exception("Only trap 'baz' messages")


class Common:
    def __init__(self):
        self.bars = 0


def loop(msg_queue):
    # msg_queue should be accessible to another thread which is
    # handling IPC traffic or otherwise generating events to be
    # consumed by the state machine

    fsm = mortise.StateMachine(
        initial_state=Foo,
        final_state=mortise.DefaultStates.End,
        default_error_state=ErrorState,
        msg_queue=msg_queue,
        log_fn=print,
        trap_fn=trap_msg,
        common_state=Common())

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
        idx = random.randint(0, 2)
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
