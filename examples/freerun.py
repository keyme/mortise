#!/usr/bin/env python3
import queue

import mortise
from mortise import State

class Ping(State):
    def on_enter(self, st):
        print("Entering Ping")

    def on_state(self, st):
        print("Ping")
        return Pong

class Pong(State):
    def on_state(self, st):
        print("Pong")
        return Ping

    def on_leave(self, st):
        print("Leaving Pong")

class ErrorState(State):
    def on_state(self, st):
        pass


def main():
    fsm = mortise.StateMachine(
        initial_state=Ping,
        final_state=mortise.DefaultStates.End,
        default_error_state=ErrorState,
        log_fn=print)

    # Runs forever
    fsm.tick()

main()
