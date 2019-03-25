#!/usr/bin/env python3
import mortise
from mortise import State


class Ping(State):
    RETRIES = 3

    def on_enter(self, st):
        print("Entering Ping")

    def on_state(self, st):
        print("Ping")
        return self

    def on_fail(self, st):
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
    fsm.start_non_blocking()

main()
