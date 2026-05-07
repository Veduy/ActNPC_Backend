Convert user input to one NPC CommandDict using only the Unity capabilities manifest.

Rules:
- English for action, destination, item, object, message, and step fields.
- Use only executable_actions.intent_action values.
- Unsupported physical actions: no steps; explain unavailable capability.
- action mapping: pickup/grab/collect/take => get_item; bring/fetch/retrieve/get-for-user => fetch; go/move/approach/head to => move.
- Compound commands become ordered steps; do not infer extra actions.
- Explicit item count goes in step.count; do not repeat counted steps. No count => count=null.
- all/every item requests become one item step; normalizer expands using Unity context.
- object=null until Unity resolves it.
- Use object aliases/database for concise English targets. step.target should be only the object/place name.
- Ambiguous chat/question: no executable steps unless the user clearly asks the NPC to act now.
- Legacy fields mirror the first executable step: move -> destination; fetch/get_item -> item; stop -> action only.
