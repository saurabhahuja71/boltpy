"""Shared live todo list used by agent tools and the TUI side panel."""
from __future__ import annotations
import time
from dataclasses import dataclass, field

@dataclass
class Todo:
    """A single todo item with stable id."""
    id: str
    description: str
    completed: bool = False
    created: float = field(default_factory=time.time)

class TodoStore:
    """In-memory todo list shared between the agent tools and the panel."""
    def __init__(self) -> None:
        self._todos: list[Todo] = []
        self._next_id = 1

    def add(self, description: str) -> Todo:
        todo = Todo(id=str(self._next_id), description=description.strip())
        self._next_id += 1
        self._todos.append(todo)
        return todo

    def get(self, todo_id: str) -> Todo | None:
        return next((todo for todo in self._todos if todo.id == todo_id), None)

    def update(self, todo_id: str, description: str) -> bool:
        todo = self.get(todo_id)
        if todo is None or not description.strip():
            return False
        todo.description = description.strip()
        return True

    def complete(self, todo_id: str) -> bool:
        todo = self.get(todo_id)
        if todo is None:
            return False
        todo.completed = True
        return True

    def delete(self, todo_id: str) -> bool:
        todo = self.get(todo_id)
        if todo is None:
            return False
        self._todos.remove(todo)
        return True

    def clear(self) -> None:
        self._todos.clear()
        self._next_id = 1

    def items(self) -> list[Todo]:
        return list(self._todos)

    def open_count(self) -> int:
        return sum(1 for todo in self._todos if not todo.completed)

    def summary(self) -> str:
        """Human-readable text returned to the model and panel."""
        if not self._todos:
            return "(no todos)"
        lines = [f"{'[x]' if todo.completed else '[ ]'} {todo.id}. {todo.description}" for todo in self._todos]
        return "\n".join(lines)

todo_store = TodoStore()
