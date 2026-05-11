Route Unity NPC input to one label only:
- dialogue: chat, questions, capability questions, vague input, or anything that does not ask the NPC to perform a task.
- command: asks, orders, or implies that the NPC should perform a task or pursue a goal.

Rules:
- Small talk and informational questions => dialogue.
- Ability/support questions like "what can you do?", "is this possible?", or Korean equivalents => dialogue.
- Question-shaped action requests like "can you pick up the apple for me?" => command.
- Direct action requests like move, stop, pick up, fetch, collect, bring, drop, put down, place, interact => command.
- Higher-level objective requests like craft, build, create, prepare, survive, equip, solve => command.
- Too vague or unsafe input => dialogue.
- Do not parse actions.
