Rewrite the parsed NPC command into the final minimal executable step list.

Rules:
- Each step must be one minimum executable unit.
- For get_item, one step means picking up one item instance.
- For fetch, one step means one fetch request and will become MOVE_TO + GET_ITEM for one item instance.
- If the user asks for all/every matching item, repeat get_item/fetch once per matching object in Unity context.
- Preserve explicit count values that are already present in step.count unless expanding all/every matching item requests.
- Preserve later user requests in their original order after expanding all/every item requests.
- Use object ids from Unity context. object_id is a type id, so repeated item steps may use the same object id.
- Do not add any field outside the schema.
- Keep legacy top-level fields aligned with the first final step.

Original user message:
$user_message

Parsed command:
$command_data_json

Unity context:
$client_context_json
