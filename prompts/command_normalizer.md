Rewrite the parsed NPC command into the final minimal executable step list.

Rules:
- Each step must be one minimum executable unit.
- For get_item, one step means picking up one item instance.
- For fetch, one step means one fetch request and will become MOVE_TO + GET_ITEM for one item instance.
- If the user asks for all/every matching item, repeat get_item/fetch once per matching object in Unity context.
- If the user asks for a specific count, repeat get_item/fetch min(requested_count, matching_object_count) times.
- If fewer matching objects exist than requested, only emit steps for the objects that exist.
- Preserve later user requests in order. For example, "pick up 2 apples then move to tree" becomes get_item, get_item, move.
- Use object ids from Unity context. object_id is a type id, so repeated item steps may use the same object id.
- Do not add any field outside the schema.
- Keep legacy top-level fields aligned with the first final step.

Original user message:
$user_message

Parsed command:
$command_data_json

Unity context:
$client_context_json
