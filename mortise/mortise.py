#!/usr/bin/env python3
""" mortise is a finite state machine library.
"""

from threading import Timer
import collections
from datetime import datetime
from queue import Queue


BLOCKING_RETURNS = [None, True]


class StateRetryLimitError(Exception):
    pass


class StateMachineComplete(Exception):
    pass


class MissingOnStateHandler(Exception):
    pass


class StateTimedOut(Exception):
    pass


class InvalidPushError(Exception):
    pass


class EmptyStateStackError(Exception):
    pass


class NoPushedStatesError(Exception):
    pass


class NonBlockingStalled(Exception):
    pass


class BlockedInUntimedState(Exception):
    def __init__(self, state):
        super().__init__("Blocking on state without a timer: {}"
                         .format(state_name(state)))
        self.state = state


class Push(object):
    def __init__(self, *args):
        self.push_states = args
        self.name = 'Push'

Pop = collections.namedtuple('Pop', [])


def state_name(descriptor):
    if hasattr(descriptor, '__name__'):
        return descriptor.__name__
    elif hasattr(descriptor, 'name'):
        return descriptor.name


def base_state_name(descriptor):
    if hasattr(descriptor, '__bases__'):
        return descriptor.__bases__[0].__name__
    elif hasattr(descriptor, '__class__'):
        return descriptor.__class__.__bases__[0].__name__


class State:
    """States are the workhorses of the mortise library. User states
    should inherit from State and provide
    on_enter/on_leave/on_fail/on_timeout methods (as appropriate,
    pass-through defaults are provided), and MUST provide on on_state
    handler.

    on_enter/on_leave are fired once on entry and on leaving the
    state. These methods should return nothing as they are incapable
    of affecting the transitioning of the state machine.

    on_state is the main/required method of each state. on_state
    should return one of several options:

    * None/True - A wait state, The state is waiting on some external
    stimulus (like a message).

        * Returning 'True' indicates that the state swallowed the message that
        we were passed. On the next tick, the same state will begin from its
        on_enter method. This is a transition from the current state back to a
        new instance of the same state.

        * Returning 'None' indicates that the state did nothing with the
        message (which will cause the message to be trapped by the
        encapsulating FSM). On the next tick, the on_enter method is bypassed,
        and the state will begin from its on_state method. This is a wait in
        the current instance of the state, for the right message needed to
        transition.

    * Its own class descriptor (not an instance!) - This is a retry.
    The state will transition to an uninitialized state and will
    restart execution from on_enter. Note that this is a tool for handling
    "bad input", and the FSM will not tick, and no new message will be acquired.

    * Another state's class descriptor (not an instance!) - This is a
    transition. The FSM will fire the current on_leave handler (if
    it exists) and transition to the next state.

    States may also provide TIMEOUT and RETRIES class variables.

    TIMEOUT specifies the duration of a failsafe timer in seconds that
    is started when a state is entered, and cancelled when a state
    successfully transitions. If the user has provided an on_timeout
    state, it will be called in response to this event. on_timeout may
    return None, which will cause the state machine's default error
    state to be entered, the descriptor of the current state, which
    will reset the timer, or the descriptor of a specific error state.

    RETRIES specifies how many times a state may be retried before an
    error condition is flagged (default is None (infinite)). When this error
    condition occurs, the 'on_fail' handler will be called if it
    exists. on_fail may return None, which will cause the state
    machine's default error state to be entered, or the descriptor of
    a specific error state may be returned.

    """
    # TIMEOUT and RETRIES can and should be overridden by child
    # classes that require either of these bits of functionality
    TIMEOUT = None
    RETRIES = None

    def __init__(self):
        self._tries = None
        self._failsafe_timer = None
        self._reset()

    def _reset(self):
        if self.RETRIES is not None:
            self._tries = self.RETRIES + 1
        else:
            self._tries = None
        self._cancel_failsafe()
        self.has_entered = False

    def on_enter(self, shared):
        pass

    def on_leave(self, shared):
        pass

    def on_fail(self, shared):
        pass

    def on_timeout(self, shared):
        return self

    def _cancel_failsafe(self):
        if self._failsafe_timer:
            self._failsafe_timer.cancel()
            self._failsafe_timer = None

    def _start_failsafe(self, evt):
        self._failsafe_timer = evt.fsm.start_failsafe_timer(self.TIMEOUT)
        self._failsafe_timer.start()

    def _handle_retries(self):
        if self._tries is None:
            return
        elif self._tries == 0:
            raise StateRetryLimitError(
                "State: {} exceeded its maximum retry limit of {} (retries {})"
                .format(self.name, self.RETRIES, self._tries)
            )

        self._tries -= 1

    def _maybe_failsafe_timer(self, evt):
        if self.TIMEOUT:
            self._cancel_failsafe()
            self._start_failsafe(evt)

    def _wrap_enter(self, evt, fn=None):
        self._handle_retries()

        if fn:
            fn(evt)

        self._maybe_failsafe_timer(evt)
        self.has_entered = True

    def _wrap_leave(self, evt, fn=None):
        if fn:
            fn(evt)
        self._reset()

    def _handle_timeout(self, shared_state):
        result = self.on_timeout(shared_state)
        if not result:
            result = shared_state.fsm._err_st

        # If we return ourselves from a timeout, this means that this
        # is a 'self ticking' state and we need to check our retries
        # and reset our timer
        if result is not None and state_name(result) == self.name:
            self.has_entered = False
            # Make sure that our timer is cancelled (in case out of order)
            self._cancel_failsafe()
            if isinstance(shared_state.msg, Exception):
                shared_state.msg = None

        return result

    def tick(self, shared_state):
        result = None

        if isinstance(shared_state.msg, StateTimedOut):
            result = self._handle_timeout(shared_state)
            return result
        elif isinstance(shared_state.msg, StateRetryLimitError):
            result = self.on_fail(shared_state)
            if not result:
                result = shared_state.fsm._err_st
            return result
        else:
            if not self.has_entered:
                self.on_enter_handler(shared_state)

            result = self.on_state_handler(shared_state)

            # Early exit, this is a wait condition
            if result in BLOCKING_RETURNS:
                return result

            # If a State intentionally returns itself, this is a retry and
            # we should re-enter on the next tick
            if state_name(result) == self.name:
                self.has_entered = False
                self._cancel_failsafe()
                return result

        # If we got a new state, we should fire our on_leave handler,
        # and the next state's on_enter, then return the new state
        self.on_leave_handler(shared_state)
        return result

    @property
    def name(self):
        return self.__class__.__name__

    def on_enter_handler(self, evt):
        return self._wrap_enter(evt, self.on_enter)

    def on_state_handler(self, evt):
        if hasattr(self, 'on_state'):
            return self.on_state(evt)
        else:
            raise MissingOnStateHandler(
                "State {} has no on_state handler!"
                .format(self.name)
            )

    def on_leave_handler(self, evt):
        return self._wrap_leave(evt, self.on_leave)


# End is a default state that any FSM can use
class DefaultStates:
    class End(State):
        def on_state(self, evt):
            pass


class GenericCommon:
    """This is an empty container class to hold any carry-over state in
    between FSM states should the user not provide a state container.

    """
    pass


class SharedState:
    """SharedState is passed to each state to allow states to share
    information downstream. The shared state object contains a
    reference to the higher level state machine (SharedState.fsm) and
    a common state object (SharedState.common), which may be user
    supplied during state machine instantiation.

    """
    def __init__(self, fsm, common_state):
        self.fsm = fsm

        if not common_state:
            self.common = GenericCommon()
        else:
            self.common = common_state


class StateMachine:
    """The StateMachine object is responsible for managing state
    transitions and bookkeeping shared state. On instantiation, the
    user must supply initial, final, and default error states (which
    must be subclasses of State).

    Additionally, the user MAY supply a Queue object (msg_queue) which will be
    used to pass messages into states (and relay information about timeouts and
    retry failures between the states and FSM). If no msg_queue is provided
    a default queue.Queue().empty() is used.

    The user MAY supply filter and trap functions. filter allows the
    user to pre-screen messages that may be important to the state
    machine machine, but might not be necessary to transition a state.
    trap will capture any unhandled message and can be used to raise
    exceptions or log notification messages.

    The state machine will raise an error if it stops in a state that has
    neither a timeout nor is the final state unless it is included in an
    iterable called dwell_states.

    (For a visual overview of the data flow, see mortise_data_flow.png)

    Finally, the user MAY supply a common_state class instance. This
    will be passed into each state and can be used to propagate
    information between states. If no common_state class is provided,
    an empty 'GenericCommon' will be provided (which is simply an empty class)

    """
    def __init__(self, initial_state, final_state,
                 default_error_state,
                 msg_queue=None,
                 filter_fn=None, trap_fn=None,
                 on_error_fn=None,
                 log_fn=print,
                 transition_fn=None,
                 common_state=None,
                 dwell_states=None):

        # We want to make sure that initial/final/default_err states
        # are descriptors, not instances
        for state in [initial_state, final_state, default_error_state]:
            if isinstance(state, State):
                raise TypeError(
                    "initial/final/default_error states must be class "
                    "descriptors, not instances"
                )

        self._initial_st = initial_state
        self._final_st = final_state
        self._err_st = default_error_state
        self._msg_queue = msg_queue or Queue()
        self._timeout_queue = Queue()
        self._log_fn = log_fn
        self._transition_fn = transition_fn
        self._on_err_fn = on_error_fn

        # Used for pushdown states
        self._state_stack = []

        self._current = None
        self._finished = False

        self.reset_transitions()

        self._last_trans_time = datetime.now()

        # The filter and trap functions are used to filter messages
        # (for example, common messages that apply to the process
        # rather than an individual state) and trap unhandled messages
        # (so that one could, for example, raise an exception)
        self._filter_fn = filter_fn
        self._trap_fn = trap_fn

        self._shared_state = SharedState(self, common_state)
        self._dwell_states = dwell_states or []

        self.reset()

    def start_failsafe_timer(self, duration):
        def _wrap_timeout(state, timeout):
            exception = StateTimedOut(
                "State {} timed out after {} seconds"
                .format(state, timeout)
            )
            self._timeout_queue.put(exception)
            # No-op to make sure tick state machine
            self._msg_queue.put(None)

        return Timer(duration, lambda x, y: _wrap_timeout(x, y),
                     args=[self._current.name, duration])

    def reset_transitions(self):
        # We store transitions and times separately since we don't
        # want slightly different times to affect the set of actual transitions
        self._transitions = set()
        self._transition_times = {}

    def _transition(self, trans_state):
        # If the next state is a Push, save the push states on the
        # state stack and transition to the next state, if a pop, then
        # try to pull the top state off of the stack. Otherwise, just
        # transition to the state provided
        if state_name(trans_state) == 'Push':
            if not isinstance(trans_state, Push):
                raise InvalidPushError("Push states mush be returned as an instance!")
            if len(trans_state.push_states) < 2:
                raise NoPushedStatesError("No states provided to push onto the stack")

            # Push the states on the stack in reverse order, keeping
            # the first state for the transition
            for state in reversed(trans_state.push_states[1:]):
                self._state_stack.append(state)
            next_state = trans_state.push_states[0]
        elif state_name(trans_state) == 'Pop':
            if len(self._state_stack) == 0:
                raise EmptyStateStackError("No states on stack!")
            next_state = self._state_stack.pop()
        else:
            next_state = trans_state

        # Calculate time deltas for each transition
        trans_time = datetime.now()
        trans_delta = (trans_time - self._last_trans_time).total_seconds()
        self._last_trans_time = trans_time

        if self._current:
            cur_name = state_name(self._current)
            cur_base = base_state_name(self._current)
        else:
            cur_name = "None"
            cur_base = "None"

        next_name = state_name(next_state)
        next_base = base_state_name(next_state)
        trans_tup = (cur_base, cur_name, next_base, next_name)

        self._transitions.add(trans_tup)
        self._transition_times[trans_tup] = trans_delta

        if self._log_fn:
            self._log_fn(
                "State Transition: {} -> {}"
                .format(cur_name, next_name)
            )
        if self._transition_fn:
            self._transition_fn(next_state, self._shared_state)
        # If we are preempting another state and haven't cleaned
        # up the last state, reset it without calling on_leave_handler
        if self._current and self._current.has_entered:
            self._current._reset()

        self._current = next_state()

    @property
    def graphviz_digraph(self):
        result = "digraph Cutter_State {\n\trankdir=LR;\n\tnodesep=0.5;\n"
        clusters = collections.defaultdict(set)
        transitions = ""
        cluster_transitions = set()
        for trans_tup in self._transitions:
            (first_base, first, second_base, second) = trans_tup
            clusters[first_base].add(first)
            clusters[second_base].add(second)
            cluster_transitions.add("{}->{}".format(first_base, second_base))
            trans_delta = self._transition_times[trans_tup]
            transitions += "{}->{} [ label=\"{}\" ];\n".format(first, second, trans_delta)

        for cname, cluster in clusters.items():
            result += "\tsubgraph cluster_{} {{\n".format(cname)
            result += "\t\tlabel=\"{}\"".format(cname)
            for node in cluster:
                result += "\t\t{};\n".format(node)
            result += "\tcolor=black;\n"
            result += "\t}\n\n"

        result += transitions
        result += "}\n"
        return result

    def reset(self):
        self._is_finished = False
        self._transition(self._initial_st)

    def clear_state_stack(self):
        self._state_stack = []

    def cleanup(self):
        if self._current:
            self._current._cancel_failsafe()

    @property
    def is_finished(self):
        return self._is_finished

    def start_non_blocking(self):
        self._msg_queue.put(None)
        # Still need while loop for getting errors pushed into queue
        while True:
            try:
                # Still check messages for RetryLimitException
                msg = self._msg_queue.get()
                self.tick(msg)
            except StateMachineComplete:
                raise
            if self._msg_queue.empty():
                raise NonBlockingStalled(
                    "Non-blocking state machine stalled in {}"
                    .format(state_name(self._current)))

    def tick(self, message=None):
        self._shared_state.msg = message

        # If this is a filtered message, no reason to call the state
        # machine

        is_error_state = isinstance(message, Exception)
        ok_to_filter = bool(message and self._filter_fn and not is_error_state)

        filter_exception = None
        try:
            if ok_to_filter and self._filter_fn(self._shared_state):
                return
        except Exception as e:
            # Catching any exceptions raised from filtered messages
            #  to raise them later in the try to pass to the on_error function
            filter_exception = e

        fsm_busy = True
        while fsm_busy:
            try:
                if isinstance(self._current, self._final_st):
                    self._is_finished = True

                if not self._timeout_queue.empty():
                    raise self._timeout_queue.get()

                if filter_exception:
                    raise filter_exception

                next_state = self._current.tick(self._shared_state)

                if next_state in BLOCKING_RETURNS:
                    # If we didn't return anything at all, or we
                    # returned that we swallowed the message, we'll
                    # assume that the FSM is no longer busy and is
                    # waiting on some external message to move the
                    # state along

                    if self.is_finished:
                        raise StateMachineComplete()

                    fsm_busy = False

                    # Additionally, if there is a message, and we
                    # returned nothing, we'll assume that the state
                    # didn't handle the message, and trap it.
                    should_trap = (self._shared_state.msg and
                                   next_state is None and self._trap_fn)

                    if should_trap:
                        self._trap_fn(self._shared_state)

                elif next_state:
                    # If we returned any state clear the message
                    self._shared_state.msg = None
                    if state_name(next_state) != self._current.name:
                        # Make sure timeouts are contained to their own state
                        if not self._timeout_queue.empty():
                            self._log_fn("Timed out while executing state. "
                                         "Moving on anyway.")
                            # drop timeout on the floor
                            e = self._timeout_queue.get()
                            self._log_fn(str(e))
                        # Set our current state to the next state
                        self._transition(next_state)

                fsm_busy = fsm_busy and self._msg_queue.empty()
            except (StateRetryLimitError, StateTimedOut) as e:
                self._msg_queue.put(e)
                break
            except Exception as e:
                # While it's true that 'Pokemon errors' are typically
                # in poor taste, this allows the user to selectively
                # handle error cases, and throw any error that isn't
                # explicitely handled
                next_state = None
                filter_exception = None
                if self._on_err_fn:
                    next_state = self._on_err_fn(self._shared_state, e)
                if next_state:
                    self._transition(next_state)
                else:
                    raise e

        if self.is_finished:
            raise StateMachineComplete()

        # If the state machine hasn't finished and the current state doesn't
        # have a timeout or isn't in one of the dwell_states passed in when
        # creating the state machine at the end of a tick an exception is
        # raised to indicate that the state machine is stalled.
        if (self._msg_queue.empty() and self._current.TIMEOUT is None
                and not any([isinstance(self._current, d_state)
                             for d_state in self._dwell_states])):
            raise BlockedInUntimedState(self._current)
