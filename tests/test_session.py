from boltpy.agent.session import SessionStore
from boltpy.agent.todos import TaskState


def test_session_round_trips_task_state(tmp_path):
    store = SessionStore(tmp_path)
    state = TaskState("update config", ["tests pass"], "validate", ["edit completed"], "not_run")
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "update config"}]
    store.save(messages, state.to_dict())
    assert store.load() == messages
    assert store.load_task_state() == state.to_dict()
