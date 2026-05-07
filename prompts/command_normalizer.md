Finalize the parsed CommandDict.

Rules:
- Expand all/every item requests into one get_item/fetch step per matching Unity object.
- Preserve explicit step.count unless expanding all/every.
- Preserve user order.
- Use Unity context object_id values; repeated item steps may reuse the same type id.
- Do not add fields outside the schema.
- Legacy top-level fields mirror the first final step.

Original:
$user_message

Parsed:
$command_data_json

Unity context:
$client_context_json
