Route Unity NPC input to one label only:
- general_dialogue: chat/questions not about supported NPC actions.
- capability_question: asks what NPC can do or whether an action/command is possible/supported.
- immediate_command: asks NPC to act now: move, stop, pick up, fetch, collect, bring, interact.
- goal_command: objective needing unknown prerequisites, recipes, inventory checks, planning, or decomposition: craft, build, create, prepare, survive, equip, solve.
- unsupported_or_unknown: too vague or unsafe.

Rules:
- Ability/support questions like "can you", "possible?", "what can you do?", or Korean equivalents => capability_question.
- Question-shaped action request like "can you pick up the apple for me?" => immediate_command.
- Item pickup/fetch/collect requests with a named item, even with a count, => immediate_command.
- Korean item requests like "사과 2개 주워", "사과 두 개 가져와", "사과 2개 모아" => immediate_command.
- Craft/build requests => goal_command.
- Mixed immediate action + higher-level goal => goal_command.
- goal=null except goal_command; for goal_command use concise English.
- Do not parse steps.
