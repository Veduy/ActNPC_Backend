Finalize the parsed CommandDict.

Rules:
- Expand all/every item requests into one GET_ITEM/MOVE_TO/PUT_ITEM action sequence per matching Unity item.
- Preserve user order.
- Use Unity context object_id values in action.object_id.
- Keep action.object_name as the concise object/place name. Repeated item actions may reuse the same type id.
- Do not add fields outside the schema.
