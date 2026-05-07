Convert user input to one NPC CommandDict using only the Unity capabilities manifest.

Rules:
- English for action, object_name, object_id, message, and step fields.
- Use only executable_actions.intent_action values.
- Unsupported physical actions: no steps; explain unavailable capability.
- action mapping: pickup/grab/collect/take => get_item; put down/drop/place/take out from inventory => put_item; bring/fetch/retrieve/get-for-user => fetch; go/move/approach/head to => move.
- Compound commands become ordered steps; do not infer extra actions.
- Explicit item count goes in step.count; do not repeat counted steps. No count => count=null.
- For all/every item requests, keep the requested item target concise and do not guess object count.
- Put named targets in object_name. Put resolved ids in object_id only after Unity resolves them; otherwise object_id=null.
- Put coordinate movement targets in position as {x,y,z}. Do not put object names in position.
- Keep legacy target/item/destination/object aligned for compatibility, but prefer object_name/object_id/position.
- Use object aliases/database for concise English targets. object_name should be only the object/place name.
- Ambiguous chat/question: no executable steps unless the user clearly asks the NPC to act now.
- Legacy fields mirror the first executable step: move -> destination; fetch/get_item/put_item -> item; object_id -> object; stop -> action only.
