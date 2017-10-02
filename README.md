# Mortise - A python state machine framework

Mortise is a synchronous state machine library for event based
systems.

## Features

* Synchronous state-machine event handling
* No external dependencies
* Composable / Reusable state support via pushdown automata
* State timeout and retry limit support
* Directed exception handling + state transitions on exception
* State machine visualization (requires graphviz)

## Requirements

* Python >= 3.4
* GraphViz (Optional for state machine visualization)

## Examples

### Simple state machine

``` py

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
        msg_queue=queue.Queue(),
        log_fn=print)

    # Runs forever
    fsm.tick()

main()

```

### Event based state machine

``` py

import queue

import mortise
from mortise import State

class Ping(State):
    def on_enter(self, st):
        print("Entering Ping")

    def on_state(self, st):
        if st.msg:
            print("Ping")
            return Pong

class Pong(State):
    def on_state(self, st):
        if st.msg:
            print("Pong")
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

```

## Authors

Mortise was developed at [Keyme](www.key.me) by [Jeff Ciesielski](https://github.com/Jeff-Ciesielski) and [Lianne Lairmore](https://github.com/knithacker)
