import mortise
import unittest


class FakeCommon:
    def __init__(self, entries):
        self.__dict__.update(**entries)


class FakeFSM:
    def __init__(self, init_state):
        self.msg = None
        if isinstance(init_state, dict):
            self.common = FakeCommon(init_state)
        else:
            self.common = init_state


def makeTestingInternalState(dictState):
    """Takes a dictionary mirroring the internal state
       a mortise State expects to see and creates that
       object to be used in testing correct transisitions"""
    return FakeFSM(dictState)


class MortiseTest(unittest.TestCase):

    def _next_state(self, fsm, state):
        while True:
            try:
                result_state = state.tick(fsm)
                if result_state is not None:
                    break
            except (mortise.StateRetryLimitError,
                    mortise.StateTimedOut) as e:
                fsm.msg = e
        return result_state

    def assertNextState(self, mortise_state, next_state,
                        initial_state=None, msg=None):
        current_state = mortise_state()
        fake_fsm = FakeFSM(initial_state or {})
        fake_fsm.msg = msg
        result_state = self._next_state(fake_fsm, current_state)
        self.assertIs(result_state, next_state)

    def assertTimedOutState(self, mortise_state, next_state,
                            initial_state=None):
        self.assertNextState(mortise_state, next_state, initial_state,
                             mortise.StateTimedOut())

    def assertFailState(self, mortise_state, next_state, initial_state=None):
        self.assertNextState(mortise_state, next_state, initial_state,
                             mortise.StateRetryLimitError())

    def _single_transition(self, mortise_state, initial_state=None, msg=None):
        current_state = mortise_state()
        fake_fsm = FakeFSM(initial_state or {})
        fake_fsm.msg = msg
        return current_state.tick(fake_fsm)

    def assertNoTransition(self, mortise_state, initial_state=None, msg=None):
        self.assertIsNone(
            self._single_transition(mortise_state, initial_state, msg))

    def assertSomeTransition(self, mortise_state, initial_state=None,
                             msg=None):
        self.assertIsNotNone(
            self._single_transition(mortise_state, initial_state, msg))
